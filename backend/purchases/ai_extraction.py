"""Extraction locale des factures par IA visuelle avec Ollama.

Le modèle lit les pages du PDF, avec leur mise en page, ou à défaut le texte OCR,
et renvoie des données structurées avec un schéma JSON imposé. Le résultat
est converti dans le même format que l'extracteur à règles
(ExtractedPurchaseInvoice), puis contrôlé : ICE de la société acheteuse écarté,
cohérence quantité × prix = total, somme des lignes = total HT, HT + TVA = TTC.

Les images et le texte sont envoyés uniquement au service Ollama configuré,
normalement le conteneur local du même Docker Compose.
"""

import base64
import json
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .extraction import (
    CENT,
    NATURE_EXPENSE,
    NATURE_GOODS,
    NATURE_RENTAL,
    NATURE_SALE,
    NATURE_SERVICE,
    NATURE_UNKNOWN,
    ZERO,
    ExtractedInvoiceLine,
    ExtractedPurchaseInvoice,
    hamming,
    ice_digits,
)


NATURES = (NATURE_GOODS, NATURE_RENTAL, NATURE_SERVICE, NATURE_EXPENSE, NATURE_SALE, NATURE_UNKNOWN)

_NUMBER = {"type": ["number", "null"]}
_TEXT = {"type": ["string", "null"]}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["facture", "avoir", "proforma", "devis", "ticket", "bon_de_livraison", "bon_de_commande", "autre"],
            "description": "Type du document principal.",
        },
        "is_sale_invoice": {
            "type": "boolean",
            "description": "Vrai si la facture est ÉMISE par la société acheteuse (vente), faux si elle est reçue d'un fournisseur.",
        },
        "nature": {
            "type": "string",
            "enum": list(NATURES),
            "description": (
                "MARCHANDISES : achat de biens (articles, matériel, matières, consommables). "
                "LOCATION : location de matériel, véhicules, lieux. SERVICE : prestation, main-d'œuvre, "
                "transport, abonnement, honoraires, traiteur, animation. FRAIS : hôtel, restaurant, billets, "
                "carburant, péage. VENTE : facture émise par la société. INDETERMINEE : impossible à dire."
            ),
        },
        "supplier": {
            "type": "object",
            "properties": {
                "name": _TEXT,
                "ice": {"type": ["string", "null"], "description": "ICE du FOURNISSEUR (15 chiffres), jamais celui du client."},
                "if_number": _TEXT,
                "rc": _TEXT,
                "city": _TEXT,
                "address": _TEXT,
                "contact": _TEXT,
            },
            "required": ["name", "ice"],
        },
        "buyer": {
            "type": "object",
            "properties": {
                "name": _TEXT,
                "tax_id": _TEXT,
                "billing_address": _TEXT,
                "delivery_address": _TEXT,
            },
        },
        "invoice_number": _TEXT,
        "purchase_order_number": _TEXT,
        "invoice_date": {"type": ["string", "null"], "description": "Format AAAA-MM-JJ."},
        "due_date": {"type": ["string", "null"], "description": "Format AAAA-MM-JJ."},
        "currency": {"type": "string", "description": "Code ISO : MAD, EUR, USD…"},
        "totals": {
            "type": "object",
            "properties": {
                "subtotal_ht": _NUMBER,
                "discount_amount": _NUMBER,
                "shipping_amount": _NUMBER,
                "net_ht": _NUMBER,
                "tax_amount": _NUMBER,
                "total_ttc": _NUMBER,
                "amount_due": _NUMBER,
            },
            "required": ["net_ht", "tax_amount", "total_ttc"],
        },
        "payment": {
            "type": "object",
            "properties": {
                "method": _TEXT,
                "terms": _TEXT,
                "iban_or_rib": _TEXT,
                "swift_or_bic": _TEXT,
            },
        },
        "tax_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"rate": {"type": "number"}, "base": _NUMBER, "amount": _NUMBER},
                "required": ["rate"],
            },
        },
        "lines": {
            "type": "array",
            "description": "Lignes d'articles ou de prestations de la FACTURE (pas du bon de livraison ni du bon de commande joints).",
            "items": {
                "type": "object",
                "properties": {
                    "reference": _TEXT,
                    "description": {"type": "string", "description": "Désignation recopiée telle qu'écrite sur la facture."},
                    "quantity": _NUMBER,
                    "unit": _TEXT,
                    "unit_price_ht": _NUMBER,
                    "discount_percent": _NUMBER,
                    "tax_rate": {"type": ["number", "null"], "description": "Taux de TVA en %, ex. 20."},
                    "total_ht": _NUMBER,
                    "total_ttc": _NUMBER,
                },
                "required": ["description", "quantity", "unit_price_ht", "total_ht"],
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Doutes de lecture : zones illisibles, montants incertains, document incomplet…",
        },
    },
    "required": ["document_type", "is_sale_invoice", "nature", "supplier", "invoice_number",
                 "invoice_date", "currency", "totals", "lines", "warnings"],
}

SYSTEM_PROMPT = """Tu es un assistant comptable marocain chargé de lire des factures d'achat scannées.
Tu enregistres les données avec l'outil fourni, sans rien inventer : une valeur illisible ou absente vaut null.

Règles :
- La société acheteuse (le client) est {buyer_name}, ICE {buyer_ice}. Son nom et son ICE ne sont JAMAIS ceux du fournisseur.
- Le PDF peut contenir la facture puis un bon de livraison, un bon de commande ou d'autres pièces : n'extrais que les lignes de la facture, sans doublons.
- Recopie chaque désignation telle qu'elle est écrite. Une ligne de remise ou de frais (livraison, transport) est une ligne à part.
- Les nombres sont au format décimal avec un point (1 234,56 devient 1234.56).
- Si la facture n'indique que des prix TTC, renseigne total_ttc et calcule unit_price_ht et total_ht hors taxe avec le taux de TVA indiqué.
- Si une même ligne est répartie sur plusieurs lignes de texte, réunis-la en une seule ligne.
- Vérifie que quantité × prix unitaire HT (après remise) = total HT de la ligne, et que la somme des lignes correspond au total HT. Signale toute incohérence dans warnings.
- Un ticket de caisse est un document de type « ticket » ; ses lignes sont à extraire comme celles d'une facture.
"""


class AiExtractionError(Exception):
    """L'extraction par IA n'a pas abouti pour ce document."""


@dataclass
class AiExtractionResult:
    extracted: ExtractedPurchaseInvoice
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = None
    seconds: float = 0.0
    document_type: str = ""
    used_pdf: bool = False
    raw: dict = field(default_factory=dict)


def _decimal(value, places=CENT):
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number.quantize(places, rounding=ROUND_HALF_UP) if places else number


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


class OllamaInvoiceExtractor:
    def __init__(
        self,
        *,
        api_url=None,
        model=None,
        timeout=None,
        max_pages=None,
        http_open=None,
        excluded_ices=(),
        excluded_names=(),
    ):
        self.api_url = (api_url or getattr(settings, "OLLAMA_API_URL", "http://ollama:11434")).rstrip("/")
        self.model = model or getattr(settings, "OLLAMA_MODEL", "qwen2.5vl:3b")
        self.timeout = timeout or getattr(settings, "OLLAMA_TIMEOUT", 900)
        self.max_pages = max_pages or getattr(settings, "OLLAMA_MAX_PAGES", 10)
        self.excluded_ices = tuple(ice_digits(ice) for ice in excluded_ices if ice)
        self.excluded_names = tuple(excluded_names)
        self.http_open = http_open or urlopen

    # ------------------------------------------------------------ appel à Ollama
    def extract_document(self, *, pdf_bytes=None, text="", title="", page_count=None):
        use_pdf = bool(pdf_bytes) and (page_count is None or page_count <= self.max_pages)
        if use_pdf:
            images = [
                base64.standard_b64encode(image).decode("ascii")
                for image in self._render_pdf_pages(pdf_bytes)
            ]
            instruction = "Lis cette facture et enregistre ses données avec l’outil."
        else:
            images = []
            instruction = f"Lis ce texte OCR de facture et enregistre ses données :\n\n{(text or '')[:60000]}"
        if title:
            instruction += f" Titre du document dans l’archive : « {title} »."
        instruction += " Réponds uniquement avec le JSON conforme au schéma fourni."

        system = SYSTEM_PROMPT.format(
            buyer_name=self.excluded_names[0] if self.excluded_names else "la société",
            buyer_ice=self.excluded_ices[0] if self.excluded_ices else "inconnu",
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": instruction, "images": images},
            ],
            "format": INVOICE_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        }
        request = Request(
            f"{self.api_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with self.http_open(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise AiExtractionError(
                f"Ollama a répondu avec l’erreur HTTP {error.code} : {detail}"
            ) from error
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
            raise AiExtractionError(
                f"Le moteur IA local Ollama est inaccessible : {error}"
            ) from error
        seconds = time.monotonic() - started

        try:
            data = json.loads(response_payload["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise AiExtractionError("Ollama n’a pas renvoyé de données structurées valides.") from error
        if not isinstance(data, dict):
            raise AiExtractionError("Ollama n’a pas renvoyé un objet JSON.")
        input_tokens = int(response_payload.get("prompt_eval_count") or 0)
        output_tokens = int(response_payload.get("eval_count") or 0)
        return AiExtractionResult(
            extracted=self.to_extracted(data),
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=Decimal("0"),
            seconds=round(seconds, 1),
            document_type=str(data.get("document_type") or ""),
            used_pdf=use_pdf,
            raw=data,
        )

    def _render_pdf_pages(self, pdf_bytes):
        try:
            import fitz

            with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                if not len(document):
                    raise AiExtractionError("Le PDF ne contient aucune page.")
                if len(document) > self.max_pages:
                    raise AiExtractionError(
                        f"Le PDF contient {len(document)} pages ; la limite locale est {self.max_pages}."
                    )
                matrix = fitz.Matrix(1.5, 1.5)
                return [
                    page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                    for page in document
                ]
        except AiExtractionError:
            raise
        except Exception as error:
            raise AiExtractionError(f"Impossible de convertir le PDF en images : {error}") from error

    # ------------------------------------------------------------ conversion et contrôles
    def to_extracted(self, data):
        notes = [f"Extraction IA locale Ollama ({self.model})."]
        supplier = data.get("supplier") or {}
        supplier_ice = ice_digits(supplier.get("ice"))
        if len(supplier_ice) != 15:
            supplier_ice = ""
        if supplier_ice and any(hamming(supplier_ice, own) <= 2 for own in self.excluded_ices):
            notes.append("L’ICE proposé était celui de la société acheteuse : il a été écarté.")
            supplier_ice = ""
        supplier_name = " ".join(str(supplier.get("name") or "").split())[:255]
        if supplier_name and any(
            name.casefold().split()[0] in supplier_name.casefold() for name in self.excluded_names if name.split()
        ):
            supplier_name = ""

        totals = data.get("totals") or {}
        subtotal_ht = _decimal(totals.get("subtotal_ht"))
        discount_amount = _decimal(totals.get("discount_amount"))
        shipping_amount = _decimal(totals.get("shipping_amount"))
        net_ht = _decimal(totals.get("net_ht"))
        tax_amount = _decimal(totals.get("tax_amount"))
        total_ttc = _decimal(totals.get("total_ttc"))
        amount_due = _decimal(totals.get("amount_due"))
        buyer = data.get("buyer") or {}
        payment = data.get("payment") or {}
        rates = {
            _decimal(item.get("rate"), None)
            for item in data.get("tax_breakdown") or []
            if _decimal(item.get("rate"), None) is not None
        }
        single_rate = next(iter(rates)) if len(rates) == 1 else None
        if single_rate is None and net_ht and tax_amount:
            single_rate = (tax_amount / net_ht * 100).quantize(Decimal("0.01"))

        lines = []
        for item in data.get("lines") or []:
            line = self._line(item, single_rate)
            if line is not None:
                lines.append(line)

        lines_total = sum((line.total_ht for line in lines), ZERO)
        balanced = bool(lines) and net_ht is not None and abs(lines_total - net_ht) <= Decimal("0.05")
        totals_ok = None not in (net_ht, tax_amount, total_ttc) and abs(net_ht + tax_amount - total_ttc) <= Decimal("0.05")

        confidence = Decimal(55)
        confidence += 20 if balanced else 0
        confidence += 10 if totals_ok else 0
        confidence += 5 if supplier_ice else 0
        confidence += 5 if data.get("invoice_number") else 0
        confidence = min(confidence, Decimal(95))

        if balanced:
            notes.append("Somme des lignes = total HT.")
        elif lines and net_ht is not None:
            notes.append(f"La somme des lignes ({lines_total} HT) diffère du total HT ({net_ht}).")
        if totals_ok:
            notes.append("Totaux cohérents : HT + TVA = TTC.")
        elif None not in (net_ht, tax_amount, total_ttc):
            notes.append("Totaux incohérents : HT + TVA ≠ TTC.")
        if not supplier_ice:
            notes.append("L’ICE fournisseur doit être complété manuellement.")
        for warning in data.get("warnings") or []:
            notes.append(f"Remarque de l’IA : {warning}")
        notes.append("Toutes les lignes extraites doivent être vérifiées avant validation.")

        nature = str(data.get("nature") or NATURE_UNKNOWN)
        if data.get("is_sale_invoice"):
            nature = NATURE_SALE
        if nature not in NATURES:
            nature = NATURE_UNKNOWN

        currency = str(data.get("currency") or "MAD").strip().upper()[:3] or "MAD"
        if currency in ("DH", "DHS"):
            currency = "MAD"
        return ExtractedPurchaseInvoice(
            supplier_name=supplier_name,
            supplier_ice=supplier_ice,
            invoice_number=" ".join(str(data.get("invoice_number") or "").split())[:100],
            invoice_date=_date(data.get("invoice_date")),
            due_date=_date(data.get("due_date")),
            currency=currency,
            net_ht=net_ht,
            tax_amount=tax_amount,
            total_ttc=total_ttc,
            lines=tuple(lines),
            confidence=confidence,
            notes=" ".join(notes),
            nature=nature,
            nature_details=f"Nature lue par l’IA ; document : {data.get('document_type') or '?'}.",
            totals_method="IA",
            tax_rate=single_rate,
            purchase_order_number=self._text(data.get("purchase_order_number"), 100),
            supplier_address=self._text(supplier.get("address"), 2000),
            supplier_contact=self._text(supplier.get("contact"), 255),
            supplier_if=self._text(supplier.get("if_number"), 30),
            supplier_rc=self._text(supplier.get("rc"), 30),
            buyer_name=self._text(buyer.get("name"), 255),
            buyer_tax_id=ice_digits(buyer.get("tax_id"))[:30],
            billing_address=self._text(buyer.get("billing_address"), 2000),
            delivery_address=self._text(buyer.get("delivery_address"), 2000),
            subtotal_ht=subtotal_ht,
            discount_amount=discount_amount,
            shipping_amount=shipping_amount,
            amount_due=amount_due,
            payment_method=self._text(payment.get("method"), 100),
            payment_terms=self._text(payment.get("terms"), 255),
            supplier_iban=self._text(payment.get("iban_or_rib"), 64),
            supplier_swift=self._text(payment.get("swift_or_bic"), 32),
        )

    @staticmethod
    def _text(value, limit):
        return " ".join(str(value or "").split())[:limit]

    @staticmethod
    def _line(item, invoice_rate):
        description = " ".join(str(item.get("description") or "").split())
        if not description:
            return None
        quantity = _decimal(item.get("quantity"), Decimal("0.0001"))
        unit_price = _decimal(item.get("unit_price_ht"), Decimal("0.0001"))
        total_ht = _decimal(item.get("total_ht"))
        discount = _decimal(item.get("discount_percent")) or ZERO
        if quantity is None:
            quantity = Decimal(1)
        if total_ht is None and unit_price is not None:
            total_ht = (quantity * unit_price * (1 - discount / 100)).quantize(CENT)
        if unit_price is None and total_ht is not None and quantity:
            unit_price = (total_ht / quantity).quantize(Decimal("0.0001"))
        if total_ht is None or unit_price is None:
            return None
        if quantity < 0 or unit_price < 0 or total_ht < 0:
            # Les montants négatifs (remises) ne sont pas acceptés par la base : la remise
            # reste visible dans l'écart entre la somme des lignes et le total HT.
            return None
        rate = _decimal(item.get("tax_rate"))
        if rate is None:
            rate = invoice_rate if invoice_rate is not None else ZERO
        if not ZERO <= rate <= 100:
            rate = ZERO
        tax = (total_ht * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        expected = (quantity * unit_price * (1 - discount / 100)).quantize(CENT)
        consistent = abs(expected - total_ht) <= max(Decimal("0.05"), total_ht * Decimal("0.01"))
        return ExtractedInvoiceLine(
            description=description[:1000],
            quantity=quantity,
            unit_price_ht=unit_price,
            total_ht=total_ht,
            tax_rate=rate,
            tax_amount=tax,
            total_ttc=total_ht + tax,
            source_text="(lu par l’IA)",
            confidence=Decimal(90) if consistent else Decimal(65),
            reference=" ".join(str(item.get("reference") or "").split())[:100],
            unit=" ".join(str(item.get("unit") or "").split())[:30],
            discount_percent=discount if ZERO <= discount <= 100 else ZERO,
        )
