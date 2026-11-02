import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


AMOUNT_TOKEN = r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2,4})"
ZERO = Decimal("0")
CENT = Decimal("0.01")
LEGAL_TAX_RATES = (Decimal("20"), Decimal("14"), Decimal("10"), Decimal("7"))
TOTAL_LABELS = (
    "total",
    "tva",
    "net a payer",
    "net à payer",
    "montant total",
    "prime totale",
    "acompte",
    "solde",
)

# Nature de la facture : seules les factures de marchandises alimentent le stock.
NATURE_GOODS = "MARCHANDISES"
NATURE_RENTAL = "LOCATION"
NATURE_SERVICE = "SERVICE"
NATURE_EXPENSE = "FRAIS"
NATURE_UNKNOWN = "INDETERMINEE"

# Méthode qui a permis de lire les totaux.
TOTALS_FROM_TRIPLET = "HT+TVA=TTC"
TOTALS_FROM_WORDS = "MONTANT_EN_LETTRES"
TOTALS_FROM_LABELS = "LIBELLES"


@dataclass(frozen=True)
class ExtractedInvoiceLine:
    description: str
    quantity: Decimal
    unit_price_ht: Decimal
    total_ht: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total_ttc: Decimal
    source_text: str
    confidence: Decimal
    reference: str = ""
    unit: str = ""
    discount_percent: Decimal = ZERO


@dataclass(frozen=True)
class ExtractedPurchaseInvoice:
    supplier_name: str
    supplier_ice: str
    invoice_number: str
    invoice_date: date | None
    due_date: date | None
    currency: str
    net_ht: Decimal | None
    tax_amount: Decimal | None
    total_ttc: Decimal | None
    lines: tuple[ExtractedInvoiceLine, ...]
    confidence: Decimal
    notes: str
    nature: str = NATURE_UNKNOWN
    nature_details: str = ""
    totals_method: str = ""
    tax_rate: Decimal | None = None


def parse_decimal(value):
    normalized = (value or "").strip().replace(" ", "")
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    else:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_date(value):
    match = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", value.strip())
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def ice_digits(value):
    return re.sub(r"\D", "", value or "")


def hamming(first, second):
    return sum(a != b for a, b in zip(first, second)) + abs(len(first) - len(second))


def is_same_ice(first, second, *, tolerance=1):
    """Deux ICE identiques à `tolerance` chiffres près (erreurs de lecture OCR)."""
    first, second = ice_digits(first), ice_digits(second)
    return len(first) == len(second) == 15 and hamming(first, second) <= tolerance


# ---------------------------------------------------------------- montants
_NUMBER = re.compile(r"(?<![\d,.])(?:\d{1,3}(?:[ . ]\d{3})+|\d+)[,.]\d{2}(?!\d)")
_NUMBER_WITH_CURRENCY = re.compile(
    r"(?:MAD|DH)\s?(\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{1,4})?(?!\d)"
    r"|(?<![\d,.])(\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2})?\s*(?:dhs?|mad|dirhams?)\b",
    re.IGNORECASE,
)
_MAX_AMOUNT = Decimal("50000000")


def _to_amount(raw):
    raw = re.sub(r"[\s ]", "", raw)
    match = re.match(r"^(.*?)(?:[,.](\d{1,2}))?$", raw)
    integer = re.sub(r"[.,]", "", match.group(1)) or "0"
    return Decimal(f"{integer}.{match.group(2) or '0'}").quantize(CENT)


def amounts_in(text):
    """Tous les montants lisibles d'un texte OCR (1 234,56 / 1.234,56 / 1500 DH / MAD1500)."""
    values = {_to_amount(raw) for raw in _NUMBER.findall(text)}
    for match in _NUMBER_WITH_CURRENCY.finditer(text):
        values.add(_to_amount(match.group(1) or match.group(2)))
    return sorted(value for value in values if ZERO < value < _MAX_AMOUNT)


def find_tax_triplet(text, *, target_ttc=None):
    """Cherche HT + TVA = TTC avec un taux légal marocain.

    Renvoie (HT, TVA, TTC, taux) pour le plus grand TTC cohérent, ou celui dont
    le TTC vaut `target_ttc` lorsqu'il est connu (montant en lettres).
    """
    values = amounts_in(text)
    available = set(values)
    best = None
    for net in values:
        if net < 10:
            continue
        for tax in values:
            if tax >= net:
                break
            rate = tax / net * 100
            legal_rate = next(
                (r for r in LEGAL_TAX_RATES if abs(rate - r) < Decimal("0.15")), None
            )
            if legal_rate is None:
                continue
            total = net + tax
            if not {total - CENT, total, total + CENT} & available:
                continue
            candidate = (net, tax, total, legal_rate)
            if target_ttc is not None:
                if abs(total - target_ttc) < 1:
                    return candidate
            elif best is None or total > best[2]:
                best = candidate
    return best


_WORD_VALUES = {
    "zero": 0, "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
    "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60,
}


def french_words_to_number(text):
    total, current, previous, seen = 0, 0, None, False
    for word in re.findall(r"[a-zéèû]+", (text or "").lower()):
        if word in _WORD_VALUES:
            value = _WORD_VALUES[word]
            current += 76 if (value == 20 and previous == "quatre") else value
            seen = True
        elif word in ("cent", "cents"):
            current = (current or 1) * 100 if current < 100 else current - current % 100 + (current % 100 or 1) * 100
            seen = True
        elif word in ("mille", "milles", "mil"):
            total += (current or 1) * 1000
            current = 0
            seen = True
        elif word in ("million", "millions"):
            total += (current or 1) * 1_000_000
            current = 0
            seen = True
        previous = word
    return total + current if seen else None


def amount_in_words(text):
    """« Arrêtée la présente facture à la somme de : sept mille trois cent vingt six Dirhams »."""
    match = re.search(
        r"arr[êeé]t[ée]e?s?\s.{0,60}?somme\s+(?:en\s+dirhams\s+)?de\s*:?\s*([\s\S]{3,220}?)\b(?:dirhams?|dhs?|mad)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = french_words_to_number(match.group(1))
    if not value:
        return None
    cents = re.search(
        r"(?:dirhams?|dhs?|mad)\W+(?:et\s+)?([a-zé\s-]{3,40}?)\s*centimes",
        text[match.end() - 8: match.end() + 60],
        re.IGNORECASE,
    )
    amount = Decimal(value)
    if cents:
        amount += Decimal(french_words_to_number(cents.group(1)) or 0) / 100
    return amount.quantize(CENT) if amount >= 1 else None


# ---------------------------------------------------------------- nature de la facture
NATURE_SALE = "VENTE"

NATURE_KEYWORDS = {
    NATURE_RENTAL: (
        r"\blocations?\b", r"\blou[ée]e?s?\b", r"\bloyers?\b", r"\bleasing\b",
        r"\bcaution\b", r"\bmise\s+[àa]\s+disposition\b",
    ),
    NATURE_SERVICE: (
        r"\bprestations?\b", r"main\s*d['’]?\s*[œo]e?uvre", r"\bhonoraires\b",
        r"\bmontage\b", r"\bd[ée]montage\b", r"\binstallation\b", r"\banimation\b",
        r"\bcouverture\s+(?:photo|vid[ée]o)", r"\btransports?\b", r"\btransferts?\b",
        r"\bmanutention\b", r"\bcharge(?:ment)?\s+et\s+d[ée]charge", r"\bchargement\b",
        r"\babonnement\b", r"\bsubscription\b", r"\bmaintenance\b", r"\br[ée]paration\b",
        r"\bnettoyage\b", r"\bm[ée]nage\b", r"\bgardiennage\b", r"\bformation\b", r"\btraiteur\b",
        r"\bd[ée]placements?\b", r"\bfrais\s+de\s+services?\b", r"\btechniciens?\b",
        r"\bforfait(?:aire)?s?\b", r"\bcommission\b", r"\bassistance\b", r"\bguide\b",
        r"\bdirection\s+technique\b", r"\bcharg[ée]e?\s+de\s+prod", r"\bcollaboration\b",
        r"\bfacture\s+du\s+mois\b", r"\bp[ée]riode\s+factur[ée]e\b", r"\bpr[ée]l[èe]vement\b",
        r"\billimit[ée]\b", r"\binternet\b", r"\b[ée]lectricit[ée]\b", r"\bcommissariat\s+aux\s+comptes\b",
        r"\bagency\s+fees\b", r"\bramassage\b", r"\baccompagnement\b", r"\bcontr[ôo]le\s+des\s+acc[èe]s\b",
        r"\bdespacho\b", r"\bd[ée]claration\b", r"\bcreative\s+cloud\b", r"\bheures?\b",
        r"\bservices?\b", r"\bauto[- ]?entrepreneur\b", r"\bvoituriers?\b", r"\bbureau\s+d['’]?\s*[ée]tudes?\b",
        r"\bam[ée]nagement\b", r"\bdanseu(?:r|se)s?\b", r"\bmusiciens?\b", r"\bh[ôo]tesses?\b",
        r"\bpersonnel\b", r"\bint[ée]rim\b", r"\bindemnit[ée]s?\b", r"\bcocktail\b", r"\bbuffet\b",
        r"\bphotographe\b", r"\bs[ée]curit[ée]\b", r"\bagents?\b", r"\bdj\b", r"\bsonorisation\b",
        r"\bimpression\s+num[ée]rique\s+et\s+pose\b", r"\bpose\b",
    ),
    NATURE_EXPENSE: (
        r"\bbillets?\b", r"\bs[ée]jour\b", r"\bh[ôo]tel\b", r"\bh[ée]bergement\b",
        r"\bnuit[ée]es?\b", r"\brestaurant\b", r"\brepas\b", r"\bgas?oil\b", r"\bgazoil\b",
        r"\bgazole\b", r"\bcarburant\b", r"\bstation\s+service\b", r"\bp[ée]age\b",
        r"\btaxi\b", r"\bpax\b", r"\bd[ée]jeuners?\b", r"\bd[îi]ners?\b", r"\bmenu\b",
        r"\bcouverts\b", r"\broom\b", r"\baccommodation\b", r"\barrival\b", r"\bfolio\b",
        r"\bvoyage\b", r"\bpi[èe]ce\s+de\s+caisse\b", r"\bordre\s+de\s+d[ée]pense\b",
        r"\b(?:sgl|dbl|single|double)\s+en\s+bb\b", r"\baller\b", r"\bretour\b", r"\ba[ée]roport\b",
    ),
}
# Indices forts d'une livraison de marchandises.
GOODS_KEYWORDS = (
    r"bon\s+de\s+livraison", r"\bB\.?L\.?\s*(?:n\s*[°o]|:)", r"\bmarchandises?\b", r"\bconsignes?\b",
    r"restent?\s+la\s+propri[ée]t[ée]", r"\bcodes?\s+articles?\b",
)
NATURE_LABELS = {
    NATURE_GOODS: "marchandises",
    NATURE_RENTAL: "location",
    NATURE_SERVICE: "service",
    NATURE_EXPENSE: "frais",
}
_LINE_NATURE = {
    nature: re.compile("|".join(patterns), re.IGNORECASE)
    for nature, patterns in NATURE_KEYWORDS.items()
}


_NOT_AN_ITEM = re.compile(
    r"^(?:euro|dollar|dirham|page|t[ée]l|fax|gsm|tel/fax|adresse|bd|avenue|rue|lot|rc|r\.c|if|i\.f|rib|ice|patente|cnss|tp|date)\b"
    r"|\b(?:rib|r\.?c\s*:|i\.?f\s*:|cnss|patente|date\s+de\s+r[èe]glement)\b|\b(?:dollar|euro)\s*(?:u\.?s|canadien)?\b",
    re.IGNORECASE,
)


def line_nature(description):
    """Nature d'une ligne d'après sa désignation ; marchandises par défaut."""
    for nature in (NATURE_RENTAL, NATURE_EXPENSE, NATURE_SERVICE):
        if _LINE_NATURE[nature].search(description or ""):
            return nature
    return NATURE_GOODS


def is_sale_document(text, *, title="", own_bank_accounts=(), company_name=""):
    """Facture émise par la société elle-même (vente), à exclure des achats."""
    if re.search(r"\bVENTES?\b", title or "", re.IGNORECASE):
        return True
    first_word = (company_name or "").split()[0] if company_name else ""
    if first_word and re.search(rf"compte\s*:?\s*{re.escape(first_word)}", text, re.IGNORECASE):
        return True
    compact = re.sub(r"\s", "", text)
    for account in own_bank_accounts:
        digits = re.sub(r"\D", "", account or "")
        if len(digits) >= 10 and digits in compact:
            # Un prélèvement sur notre compte (leasing, téléphone) n'est pas une vente.
            if not re.search(r"pr[ée]l[èe]vement|domiciliation|leasing", text, re.IGNORECASE):
                return True
    return False


def classify_nature(text, lines=(), *, title="", own_bank_accounts=(), company_name=""):
    """Classe la facture : marchandises, location, service, frais, vente ou indéterminée.

    Le meilleur indice est la nature des lignes d'articles fiables
    (quantité × prix = total) ; les mots-clés du document départagent.
    """
    if is_sale_document(text, title=title, own_bank_accounts=own_bank_accounts, company_name=company_name):
        return NATURE_SALE, "Facture émise par la société (vente)."
    scores = {
        nature: sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))
        for nature, patterns in NATURE_KEYWORDS.items()
    }
    strong_goods = sum(1 for pattern in GOODS_KEYWORDS if re.search(pattern, text, re.IGNORECASE))
    line_counts = Counter(line_nature(line.description) for line in lines if line.confidence >= 70)
    goods_lines = line_counts[NATURE_GOODS]
    other_lines = sum(count for nature, count in line_counts.items() if nature != NATURE_GOODS)
    for nature, count in line_counts.items():
        if nature != NATURE_GOODS:
            scores[nature] += 2 * count

    other_nature = max((NATURE_RENTAL, NATURE_SERVICE, NATURE_EXPENSE), key=lambda key: scores[key])
    other = scores[other_nature]
    rental_mentions = len(re.findall(r"\blocation", text, re.IGNORECASE))
    if not strong_goods and rental_mentions >= 3:
        nature = NATURE_RENTAL
    elif not strong_goods and scores[NATURE_EXPENSE] >= 3 and goods_lines <= other_lines:
        nature = NATURE_EXPENSE
    elif goods_lines and goods_lines > other_lines and (
        goods_lines >= 2 or strong_goods or other <= 1
    ) and other < 6 + 2 * goods_lines:
        nature = NATURE_GOODS
    elif other >= 2 and (other_lines >= goods_lines or not goods_lines):
        nature = other_nature
    else:
        nature = NATURE_UNKNOWN
    detail = ", ".join(
        f"{NATURE_LABELS[key]} {scores[key]}" for key in (NATURE_RENTAL, NATURE_SERVICE, NATURE_EXPENSE)
    )
    return nature, (
        f"Indices : lignes marchandises {goods_lines}, autres lignes {other_lines}, "
        f"livraison {strong_goods}, {detail}."
    )


# ---------------------------------------------------------------- extracteur
class PurchaseInvoiceExtractor:
    """Extraction OCR prudente : toute facture reste à vérifier par un comptable."""

    INVOICE_NUMBER_PATTERNS = (
        re.compile(
            r"(?:n[°o]\s*(?:de\s+la\s+)?facture|facture\s+(?:n[°o]|num[eé]ro)|num[eé]ro\s+de\s+facture)\s*[:.#-]*\s*([^\n|]+?)(?=\s+date\b|$|\n|\|)",
            re.IGNORECASE,
        ),
        re.compile(
            r"facture\s+num[eé]ro[.:\s]+([^\n|]+?)(?=\s+date\b|$|\n|\|)",
            re.IGNORECASE,
        ),
    )
    # Variante tolérante aux erreurs OCR (« FACTURE Ng 290934 », « Facture # S0001 »).
    LOOSE_INVOICE_NUMBER = re.compile(
        r"factur\w*\s*(?:n\s*[°ºgso]?|num[ée]ro|no|#)?\s*\.?\s*[:.|]?\s*([A-Z_]{0,6}[-/ ]?\d[\w/\-]{1,})",
        re.IGNORECASE,
    )
    DATE_PATTERNS = (
        re.compile(
            r"(?:date\s+(?:de\s+)?facture|date\s+d['’]?[eé]mission|date)\s*[:.]?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
            re.IGNORECASE,
        ),
    )
    DUE_DATE_PATTERNS = (
        re.compile(
            r"(?:date\s+limite\s+de\s+paiement|[eé]ch[eé]ance)\D{0,20}(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
            re.IGNORECASE,
        ),
    )
    SUPPLIER_NAME_PATTERNS = (
        re.compile(
            r"(?:raison\s+sociale(?:\s+du\s+fournisseur)?|fournisseur|vendeur|[eé]mis\s+par)\s*[:#-]\s*([^\n|]+)",
            re.IGNORECASE,
        ),
    )
    # « ICE », mais aussi les lectures OCR courantes « 1CE », « IGE », « I.C.E. ».
    ICE_PATTERN = re.compile(
        r"(?<![A-Za-z])[I1l|]\s*\.?\s*[CG]\s*\.?\s*[E€]\b\.?(?:\s+(?:fournisseur|vendeur))?\s*(?:n\s*[°o]?\s*)?[:#.,;-]?\s*((?:\d[ .]?){14}\d)(?!\d)",
        re.IGNORECASE,
    )
    LEGAL_FORM_NAME = re.compile(
        r"([A-Z][A-Za-z0-9&'’. \-]{2,40}?)\s*[:,]?\s*(?:S\.?A\.?R\.?L\.?(?:\s*AU)?|SARL|S\.A\.)\b"
    )
    STE_NAME = re.compile(
        r"(?:^|\n)\s*(?:STE|ST[ÉE]|SOCI[EÉ]T[EÉ])\.?\s+([A-Z][A-Za-z0-9&'’. \-]{2,40})",
        re.IGNORECASE,
    )
    LEGAL_FORMS = {"sarl", "s.a.r.l", "s.a.r.l.", "sa", "s.a", "s.a.", "au", "ste", "sté", "société", "societe", "sas", "snc"}
    NAME_STOP_WORDS = {
        "livraison", "facture", "client", "date", "page", "total", "bon", "commande", "maroc", "marrakech",
        "casablanca", "rabat", "tanger", "agadir", "fes", "fès", "adresse", "taxe", "prof", "fax", "tel", "tél",
        "de", "du", "des", "la", "le", "les", "et", "en", "d", "l", "n°", "ice", "rc", "if", "tp", "dh", "mad",
        "capital", "siège", "social", "code", "ref", "réf", "anonyme", "responsabilité", "limitée", "conseil", "administration",
    }
    ADDRESS_WORDS = {
        "rue", "route", "avenue", "av", "bd", "boulevard", "lot", "lotissement", "quartier", "qi", "zone", "z.i",
        "immeuble", "imm", "appt", "étage", "etage", "résidence", "residence", "km", "sidi", "ghanem", "safi",
    }
    CUSTOMER_LABELS = ("client", "acheteur", "destinataire", "facturé à", "facture à")
    NOT_A_NAME = re.compile(
        r"^(?:code|n[°o]?|num[ée]ro|rc|r\.c|if|i\.f|tp|patente|cnss|tel|tél|fax|adresse|page)\b",
        re.IGNORECASE,
    )
    # Le bon de commande / bon de livraison Delight joint à la facture.
    ATTACHMENT_START = re.compile(
        r"bon\s+de\s+commande[\s\S]{0,500}?fournisseur\s*:|bon\s+de\s+livraison\s+num",
        re.IGNORECASE,
    )

    def __init__(self, *, excluded_ices=(), excluded_names=(), own_bank_accounts=()):
        self.excluded_ices = tuple(ice_digits(ice) for ice in excluded_ices if ice)
        self.excluded_names = tuple(n.casefold() for n in excluded_names if n)
        self.own_bank_accounts = tuple(own_bank_accounts or ())

    # ------------------------------------------------------------ point d'entrée
    def extract(self, text, *, title="", excluded_ices=None, excluded_names=None):
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        excluded_ices = self._excluded_ices(excluded_ices)
        excluded_names = self._excluded_names(excluded_names)
        invoice_part = self._invoice_part(text)

        supplier_name, supplier_ice, ambiguous_ice, ice_values = self._supplier_identity(
            text, excluded_ices, excluded_names
        )
        invoice_number = self._invoice_number(invoice_part)
        invoice_date, date_matches_title = self._invoice_date(invoice_part, title)
        due_date = self._first_date(invoice_part, self.DUE_DATE_PATTERNS)
        currency = self._currency(text)
        net_ht, tax_amount, total_ttc, tax_rate, totals_method = self._totals(
            text, invoice_part
        )
        lines = tuple(self._extract_lines(invoice_part, tax_rate))
        company_name = excluded_names[0] if excluded_names else ""
        if is_sale_document(
            text, title=title, own_bank_accounts=self.own_bank_accounts, company_name=company_name
        ):
            nature, nature_details = NATURE_SALE, "Facture émise par la société (vente)."
        else:
            nature, nature_details = classify_nature(invoice_part, lines)

        confidence = Decimal(30)
        confidence += 25 if totals_method in (TOTALS_FROM_TRIPLET, TOTALS_FROM_WORDS) else 0
        confidence += 10 if supplier_ice and not ambiguous_ice else 0
        confidence += 5 if invoice_number else 0
        confidence += 5 if invoice_date and date_matches_title else 0
        lines_total = sum((line.total_ht for line in lines), ZERO)
        if lines and net_ht and abs(lines_total - net_ht) <= Decimal("0.05"):
            confidence += 15
        confidence = min(confidence, Decimal(95))

        notes = []
        if ambiguous_ice:
            notes.append(
                "Plusieurs ICE ont été détectés ("
                + ", ".join(ice_values)
                + ") ; l’ICE fournisseur doit être sélectionné manuellement."
            )
        elif not supplier_ice:
            notes.append("L’ICE fournisseur doit être complété manuellement.")
        if not supplier_name:
            notes.append("Le nom de l’entreprise fournisseur doit être vérifié.")
        if totals_method == TOTALS_FROM_TRIPLET:
            notes.append(f"Totaux contrôlés : HT + TVA {tax_rate} % = TTC.")
        elif totals_method == TOTALS_FROM_WORDS:
            notes.append("Total TTC confirmé par le montant écrit en lettres.")
        elif totals_method == TOTALS_FROM_LABELS:
            notes.append("Totaux lus sans contrôle de cohérence : à vérifier.")
        if net_ht is None or total_ttc is None:
            notes.append("Les totaux doivent être complétés manuellement.")
        if invoice_date and title and not date_matches_title:
            notes.append("La date lue ne correspond pas au mois de la pièce.")
        if not lines:
            notes.append("Aucune ligne d’article fiable n’a été reconnue automatiquement.")
        elif net_ht and abs(lines_total - net_ht) > Decimal("0.05"):
            notes.append(
                f"La somme des lignes ({lines_total} HT) diffère du total HT ({net_ht})."
            )
        notes.append(f"Nature proposée : {nature.lower()}. {nature_details}")
        notes.append("Toutes les lignes extraites doivent être vérifiées avant validation.")

        return ExtractedPurchaseInvoice(
            supplier_name=supplier_name,
            supplier_ice=supplier_ice,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            currency=currency,
            net_ht=net_ht,
            tax_amount=tax_amount,
            total_ttc=total_ttc,
            lines=lines,
            confidence=confidence,
            notes=" ".join(notes),
            nature=nature,
            nature_details=nature_details,
            totals_method=totals_method,
            tax_rate=tax_rate,
        )

    def extract_supplier_identity(self, text, *, excluded_ices=None, excluded_names=None):
        """Nom et ICE du fournisseur ; l'ICE de la société acheteuse est ignoré."""
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        name, ice, ambiguous, _values = self._supplier_identity(
            text,
            self._excluded_ices(excluded_ices),
            self._excluded_names(excluded_names),
        )
        return name, ice, ambiguous

    # ------------------------------------------------------------ fournisseur
    def _excluded_ices(self, excluded_ices):
        if excluded_ices is None:
            return self.excluded_ices
        return tuple(ice_digits(ice) for ice in excluded_ices if ice)

    def _excluded_names(self, excluded_names):
        if excluded_names is None:
            return self.excluded_names
        return tuple(n.casefold() for n in excluded_names if n)

    def _supplier_identity(self, text, excluded_ices, excluded_names):
        occurrences = []  # (ice, préfixe de la ligne)
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            for match in self.ICE_PATTERN.finditer(line):
                digits = ice_digits(match.group(1))
                if len(digits) != 15:
                    continue
                # L'ICE de la société acheteuse, y compris ses variantes mal lues.
                if any(hamming(digits, own) <= 2 for own in excluded_ices):
                    continue
                occurrences.append((digits, line[: match.start()]))

        # Regroupe les lectures qui diffèrent d'un chiffre (même fournisseur).
        counts = Counter(ice for ice, _prefix in occurrences)
        groups = []
        for ice, _prefix in occurrences:
            group = next((g for g in groups if hamming(g[0], ice) <= 1), None)
            if group is None:
                groups.append([ice])
            elif ice not in group:
                group.append(ice)
        canonical = [max(group, key=lambda value: (counts[value], -group.index(value))) for group in groups]

        if len(canonical) > 1:
            # On écarte les ICE annoncés comme ceux du client.
            supplier_side = [
                ice for ice in canonical
                if not any(
                    hamming(ice, other) <= 1
                    and any(label in prefix.casefold() for label in self.CUSTOMER_LABELS)
                    for other, prefix in occurrences
                )
            ]
            if supplier_side:
                canonical = supplier_side
        ambiguous = len(canonical) > 1
        supplier_ice = canonical[0] if len(canonical) == 1 else ""

        supplier_name = self._best_supplier_name(
            text, supplier_ice, occurrences, excluded_names
        )
        supplier_name = " ".join(supplier_name.split())[:255]
        return supplier_name, supplier_ice, ambiguous, canonical

    def _best_supplier_name(self, text, supplier_ice, occurrences, excluded_names):
        """Choisit le nom le plus fiable : libellé explicite, forme juridique, ligne de l'ICE."""
        candidates = []  # (fiabilité, position, nom)
        for match in self.SUPPLIER_NAME_PATTERNS[0].finditer(text):
            candidates.append((3, match.start(), match.group(1)))
        for pattern in (self.LEGAL_FORM_NAME, self.STE_NAME):
            for match in pattern.finditer(text):
                candidates.append((2, match.start(), match.group(1)))
        if supplier_ice:
            for ice, prefix in occurrences:
                if hamming(ice, supplier_ice) <= 1:
                    candidates.append((1, 0, self._clean_company_name(prefix)))
        for _score, _position, raw in sorted(candidates, key=lambda c: (-c[0], c[1])):
            name = self._tidy_name(raw)
            if self._is_plausible_name(name) and not self._is_excluded_name(name, excluded_names):
                return name
        return ""

    @staticmethod
    def _tidy_name(raw):
        name = " ".join((raw or "").split()).strip(" -:;,.|«»\"'")
        # Coupe avant adresse, contacts et identifiants légaux.
        name = re.split(
            r"\s(?:au\s+capital|capital|r\.?\s?c\.?\s*[:n°]|i\.?\s?f\.?\s*[:n°]|ice\b|tp\s?:|patente|"
            r"taxe|cnss|c\.n\.s\.s|t[ée]l\b|fax|gsm|e-?mail|si[eè]ge|adresse|rib)",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return name.strip(" -:;,.|")[:120]

    def _is_plausible_name(self, name):
        if not name or len(name) > 60:
            return False
        letters = re.findall(r"[A-Za-zÀ-ÿ]", name)
        digits = re.findall(r"\d", name)
        if len(letters) < 3 or len(digits) > len(letters) / 3:
            return False
        if self.NOT_A_NAME.match(name) or re.match(r"\d", name):
            return False
        words = {w.casefold().strip(".") for w in re.findall(r"[\wÀ-ÿ.'’&]+", name)}
        meaningful = words - self.NAME_STOP_WORDS - self.LEGAL_FORMS
        if len(words & self.ADDRESS_WORDS) >= 2:
            return False
        return bool(meaningful) and not (words & self.ADDRESS_WORDS and len(meaningful) <= 2)

    def _clean_company_name(self, prefix):
        prefix = prefix.strip(" :-#|,.;")
        folded = prefix.casefold()
        if not prefix or any(label in folded for label in self.CUSTOMER_LABELS):
            return ""
        # Coupe avant les mentions légales : « KTI : S.A.R.L. au capital ... - TP:... ».
        prefix = re.split(
            r"\s[:\-–|]\s|\s(?:au\s+capital|capital|r\.?\s?c\.?\s|i\.?\s?f\.?\s|tp\s?:|patente|cnss|c\.n\.s\.s|t[ée]l|si[eè]ge|adresse|rib)\b",
            prefix,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        prefix = re.sub(
            r"^(?:raison\s+sociale|fournisseur|vendeur|soci[eé]t[eé])\s*[:#-]?\s*",
            "",
            prefix,
            flags=re.IGNORECASE,
        ).strip(" :-#|,.;")
        if len(re.findall(r"[A-Za-zÀ-ÿ]", prefix)) < 3 or self.NOT_A_NAME.match(prefix):
            return ""
        return prefix

    @staticmethod
    def _is_excluded_name(name, excluded_names):
        folded = (name or "").casefold()
        if not folded:
            return False
        for excluded in excluded_names:
            if excluded in folded or folded in excluded:
                return True
            # « DELIGHT EVENT MANGEMENT » : le premier mot distinctif suffit.
            first_word = next((w for w in excluded.split() if len(w) >= 4), "")
            if first_word and first_word in folded:
                return True
        return False

    # ------------------------------------------------------------ en-tête
    def _invoice_part(self, text):
        match = self.ATTACHMENT_START.search(text, 150)
        return text[: match.start()] if match else text

    def _invoice_number(self, text):
        value = self._first_group(text, self.INVOICE_NUMBER_PATTERNS)
        if value and re.search(r"\d", value) and len(value) <= 30:
            return value
        match = self.LOOSE_INVOICE_NUMBER.search(text)
        if match:
            return match.group(1).strip()[:100]
        return value

    def _invoice_date(self, text, title):
        """Date de facture ; on préfère une date du même mois que la pièce (« 79-6-2026 »)."""
        title_match = re.match(r"\s*\d+\s*[-_]\s*(\d{1,2})\s*[-_]\s*(20\d{2})", title or "")
        title_month = (int(title_match.group(1)), int(title_match.group(2))) if title_match else None

        labelled = self._first_date(text, self.DATE_PATTERNS)
        candidates = []
        for match in re.finditer(r"(?<!\d)(\d{1,2}[/.\-]\d{1,2}[/.\-](?:20)?\d{2})(?!\d)", text):
            parsed = parse_date(match.group(1))
            if parsed and 2015 <= parsed.year <= 2035:
                candidates.append(parsed)
        if labelled:
            candidates.insert(0, labelled)
        if not candidates:
            return None, False
        if title_month:
            for candidate in candidates:
                if (candidate.month, candidate.year) == title_month:
                    return candidate, True
            return candidates[0], False
        return candidates[0], True

    # ------------------------------------------------------------ totaux
    def _totals(self, text, invoice_part):
        words_ttc = amount_in_words(text)
        if words_ttc is not None and not any(abs(words_ttc - v) < Decimal("0.6") for v in amounts_in(text)):
            words_ttc = None  # montant en lettres mal lu : on ne s'en sert pas

        triplet = find_tax_triplet(invoice_part) or (
            find_tax_triplet(text) if invoice_part is not text else None
        )
        if triplet and words_ttc is not None and abs(triplet[2] - words_ttc) >= 1:
            # Plusieurs factures ou chiffres parasites : le montant en lettres tranche.
            triplet = find_tax_triplet(text, target_ttc=words_ttc)
            if triplet is None:
                return None, None, words_ttc, None, TOTALS_FROM_WORDS
        if triplet:
            net, tax, total, rate = triplet
            return net, tax, total, rate, TOTALS_FROM_TRIPLET

        net_ht = self._labelled_amount(invoice_part, ("total ht", "montant ht"))
        tax_amount = self._labelled_amount(
            invoice_part, ("total tva", "montant tva", "tva (20%)", "taxe")
        )
        total_ttc = self._labelled_amount(
            invoice_part,
            ("net a payer", "net à payer", "total t.t.c", "total ttc", "montant total à payer", "prime totale"),
        )
        if words_ttc is not None:
            return net_ht, tax_amount, words_ttc, None, TOTALS_FROM_WORDS
        if any(value is not None for value in (net_ht, tax_amount, total_ttc)):
            return net_ht, tax_amount, total_ttc, None, TOTALS_FROM_LABELS
        return None, None, None, None, ""

    # ------------------------------------------------------------ outils
    @staticmethod
    def _first_group(text, patterns):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                value = " ".join(match.group(1).strip().split())
                return value[:100]
        return ""

    @staticmethod
    def _first_date(text, patterns):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                parsed = parse_date(match.group(1))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _currency(text):
        upper_text = text.upper()
        if re.search(r"\b(?:MAD|DHS?|DIRHAMS?)\b", upper_text):
            return "MAD"
        if "€" in text:
            return "EUR"
        for currency in ("EUR", "USD", "GBP"):
            if re.search(rf"\b{currency}\b", upper_text):
                return currency
        return "MAD"

    @staticmethod
    def _labelled_amount(text, labels):
        matches = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            folded = line.casefold()
            if any(label.casefold() in folded for label in labels):
                amounts = re.findall(AMOUNT_TOKEN, line)
                if amounts:
                    amount = parse_decimal(amounts[-1])
                    if amount is not None:
                        matches.append(amount)
        return matches[-1] if matches else None

    def _extract_lines(self, text, tax_rate=None):
        for raw_line in text.splitlines():
            source = " ".join(raw_line.split())
            if len(source) < 8:
                continue
            folded = source.casefold()
            if any(folded.startswith(label) for label in TOTAL_LABELS):
                continue
            parsed = parse_item_line(source, tax_rate)
            if parsed is not None:
                yield parsed


# ---------------------------------------------------------------- lignes d'articles
_LINE_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")
# Au-delà, il s'agit d'un numéro (référence, téléphone, RIB) lu comme un nombre.
MAX_LINE_QUANTITY = Decimal("100000")
MAX_LINE_UNIT_PRICE = Decimal("10000000")
MAX_LINE_TOTAL = Decimal("50000000")
UNIT_WORDS = {
    "u", "un", "unite", "unité", "unites", "unités", "p", "pc", "pcs", "pce", "pces", "piece",
    "pièce", "pieces", "pièces", "m", "m2", "m²", "m3", "ml", "mm", "cm", "kg", "g", "l", "lt",
    "litre", "litres", "rlx", "rouleau", "rouleaux", "ct", "carton", "cartons", "boite", "boîte",
    "boites", "paquet", "paquets", "sac", "sacs", "bidon", "bidons", "lot", "lots", "ens", "ea",
    "f", "forfait", "h", "j", "jour", "jours", "pax", "bcr", "x",
}
_TOTAL_LINE = re.compile(r"\b(?:sous[- ]?total|total|net\s+[àa]\s+payer|montant\s+(?:ht|tva|ttc)|tva\s*:)", re.IGNORECASE)


def _token_values(raw):
    """Lectures possibles d'un nombre OCR (« 1.200 » = 1,2 ou 1 200)."""
    values = set()
    first = parse_decimal(raw)
    if first is not None:
        values.add(first)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        values.add(Decimal(re.sub(r"[.,]", "", raw)))
    return values


def _line_tokens(source):
    """Lectures possibles des nombres d'une ligne.

    « 12 500,00 » peut être un seul montant ou deux nombres (12 et 500,00) : on
    produit chaque découpage plausible et le contrôle quantité × prix tranche.
    """
    raw = []
    for match in _LINE_TOKEN.finditer(source):
        if source[match.end(): match.end() + 2].lstrip().startswith("%"):
            continue  # taux de TVA ou de remise
        raw.append((match.start(), match.end(), match.group()))
    results = []

    def walk(index, tokens):
        if len(results) >= 32:
            return
        if index == len(raw):
            results.append(tokens)
            return
        start, end, text = raw[index]
        walk(index + 1, tokens + [(start, end, text)])
        if re.fullmatch(r"\d{1,3}", text):
            parts, cursor = [text], index + 1
            while (
                cursor < len(raw)
                and source[raw[cursor - 1][1]: raw[cursor][0]] == " "
                and re.fullmatch(r"\d{3}(?:[.,]\d{1,2})?", raw[cursor][2])
            ):
                parts.append(raw[cursor][2])
                cursor += 1
                walk(cursor, tokens + [(start, raw[cursor - 1][1], "".join(parts))])
                if not re.fullmatch(r"\d{3}", parts[-1]):
                    break

    walk(0, [])
    return results


def parse_item_line(source, tax_rate=None):
    """Ligne d'article : désignation, quantité, prix unitaire, total (quantité × prix = total)."""
    if _TOTAL_LINE.search(source) and not re.match(r"\s*\d", source):
        return None
    best = None
    for tokens in _line_tokens(source):
        if len(tokens) < 2:
            continue
        values = [_token_values(token[2]) for token in tokens]
        last = len(tokens) - 1
        for k in range(last, max(last - 2, 0) - 1, -1):
            for total in values[k]:
                if total < Decimal("0.5"):
                    continue
                for j in range(k - 1, max(k - 4, 0) - 1, -1):
                    candidates_i = list(range(j - 1, max(j - 4, -1), -1))
                    if 0 not in candidates_i and j > 0 and not re.search(r"[A-Za-zÀ-ÿ]", source[: tokens[0][0]]):
                        candidates_i.append(0)  # quantité en début de ligne
                    for i in candidates_i:
                        for quantity in values[i]:
                            for unit_price in values[j]:
                                if (
                                    quantity <= 0
                                    or unit_price <= 0
                                    or quantity > MAX_LINE_QUANTITY
                                    or unit_price > MAX_LINE_UNIT_PRICE
                                    or total > MAX_LINE_TOTAL
                                ):
                                    continue
                                product = quantity * unit_price
                                gap = abs(product - total)
                                tolerance = max(Decimal("0.05"), total * Decimal("0.01"))
                                discount = ZERO
                                if gap > tolerance and k - j == 2:
                                    # « prix  remise%  total » : on tente la remise.
                                    for rate in values[j + 1]:
                                        if 0 < rate < 100 and abs(product * (1 - rate / 100) - total) <= tolerance:
                                            gap, discount = ZERO, rate
                                if gap > tolerance:
                                    continue
                                score = (k - j) + (j - i) + (last - k)
                                if best is None or score < best[0]:
                                    best = (score, tokens, i, j, k, quantity, unit_price, total, discount, gap)
        # Une seule quantité implicite : « désignation  prix  total » avec prix = total.
        if best is None and len(tokens) >= 2:
            for unit_price in values[-2]:
                for total in values[-1]:
                    if total >= 1 and unit_price == total:
                        best = (9, tokens, None, len(tokens) - 2, len(tokens) - 1, Decimal(1), unit_price, total, ZERO, ZERO)
    if best is None:
        return None
    _score, tokens, i, j, _k, quantity, unit_price, total, discount, gap = best

    first_used = tokens[i] if i is not None else tokens[j]
    prefix = source[: first_used[0]]
    if i is not None and not re.search(r"[A-Za-zÀ-ÿ]{3}", prefix):
        # « 6 DECOUPE SUR VINYL 20,00 120,00 » : la quantité précède la désignation.
        description = source[first_used[1]: tokens[j][0]]
    else:
        description = prefix
    description = re.sub(r"[|\[\]{}@#*“”\"_]+", " ", description)
    words = description.split()
    unit = ""
    if words and words[-1].casefold().strip(".:") in UNIT_WORDS:
        unit = words.pop().strip(".:")
    description = " ".join(words).strip(" -:;,.")
    if len(re.findall(r"[A-Za-zÀ-ÿ]", description)) < 3 or _NOT_AN_ITEM.search(description):
        return None

    reference = ""
    ref_match = re.match(r"([A-Z0-9][A-Z0-9/.\-]{3,})\s+(.*)$", description)
    if ref_match and re.search(r"\d", ref_match.group(1)) and re.search(r"[A-Za-zÀ-ÿ]{3}", ref_match.group(2)):
        reference, description = ref_match.group(1), ref_match.group(2)

    confidence = Decimal(85) if gap <= Decimal("0.05") else Decimal(75)
    if i is None:
        confidence = Decimal(60)
    total = total.quantize(CENT)
    rate = tax_rate if tax_rate is not None else ZERO
    line_tax = (total * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    return ExtractedInvoiceLine(
        description=description[:1000],
        quantity=quantity,
        unit_price_ht=unit_price,
        total_ht=total,
        tax_rate=rate,
        tax_amount=line_tax,
        total_ttc=total + line_tax,
        source_text=source,
        confidence=confidence,
        reference=reference[:100],
        unit=unit[:30],
        discount_percent=discount,
    )
