import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


AMOUNT_TOKEN = r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[,.]\d{2,4})"
ZERO = Decimal("0")
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


@dataclass(frozen=True)
class ExtractedPurchaseInvoice:
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


class PurchaseInvoiceExtractor:
    """Conservative OCR extractor that always leaves accounting review enabled."""

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

    def extract(self, text):
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        invoice_number = self._first_group(text, self.INVOICE_NUMBER_PATTERNS)
        invoice_date = self._first_date(text, self.DATE_PATTERNS)
        due_date = self._first_date(text, self.DUE_DATE_PATTERNS)
        currency = self._currency(text)
        net_ht = self._labelled_amount(text, ("total ht", "montant ht"))
        tax_amount = self._labelled_amount(
            text,
            ("total tva", "montant tva", "tva (20%)", "taxe"),
        )
        total_ttc = self._labelled_amount(
            text,
            ("net a payer", "net à payer", "total t.t.c", "total ttc", "montant total à payer", "prime totale"),
        )
        lines = tuple(self._extract_lines(text))

        found_header_values = sum(
            value not in (None, "")
            for value in (invoice_number, invoice_date, net_ht, total_ttc)
        )
        confidence = Decimal(35 + found_header_values * 10 + min(len(lines), 5) * 3)
        confidence = min(confidence, Decimal(85))
        notes = []
        if not lines:
            notes.append("Aucune ligne d’article fiable n’a été reconnue automatiquement.")
        if net_ht is None or total_ttc is None:
            notes.append("Les totaux doivent être complétés manuellement.")
        notes.append("Toutes les lignes extraites doivent être vérifiées avant validation.")

        return ExtractedPurchaseInvoice(
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
        )

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

    def _extract_lines(self, text):
        position = 0
        for raw_line in text.splitlines():
            source = " ".join(raw_line.split())
            if len(source) < 8:
                continue
            folded = source.casefold()
            if any(folded.startswith(label) for label in TOTAL_LABELS):
                continue
            parsed = self._parse_line(source)
            if parsed is None:
                continue
            position += 1
            yield parsed

    @staticmethod
    def _parse_line(source):
        leading_quantity = re.fullmatch(
            rf"[@#]?\s*(\d+(?:[,.]\d+)?)\s+(.+?)\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})",
            source,
        )
        if leading_quantity:
            quantity = parse_decimal(leading_quantity.group(1))
            unit_price = parse_decimal(leading_quantity.group(3))
            total_ht = parse_decimal(leading_quantity.group(4))
            description = leading_quantity.group(2).strip(" -|@")
            confidence = Decimal(78)
        else:
            trailing_values = re.fullmatch(
                rf"(.+?)\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})",
                source,
            )
            if trailing_values:
                description = trailing_values.group(1).strip(" -|")
                quantity = parse_decimal(trailing_values.group(2))
                unit_price = parse_decimal(trailing_values.group(3))
                total_ht = parse_decimal(trailing_values.group(4))
                confidence = Decimal(72)
            else:
                two_values = re.fullmatch(
                    rf"(.+?)\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})",
                    source,
                )
                if not two_values:
                    return None
                description = two_values.group(1).strip(" -|")
                quantity = Decimal(1)
                unit_price = parse_decimal(two_values.group(2))
                total_ht = parse_decimal(two_values.group(3))
                confidence = Decimal(55)

        if not description or not re.search(r"[A-Za-zÀ-ÿ]", description):
            return None
        if None in (quantity, unit_price, total_ht):
            return None
        if quantity < 0 or unit_price < 0 or total_ht < 0:
            return None

        calculated_total = (quantity * unit_price).quantize(Decimal("0.01"))
        if abs(calculated_total - total_ht) > max(Decimal("0.05"), total_ht * Decimal("0.03")):
            confidence = min(confidence, Decimal(45))

        return ExtractedInvoiceLine(
            description=description[:1000],
            quantity=quantity,
            unit_price_ht=unit_price,
            total_ht=total_ht,
            tax_rate=ZERO,
            tax_amount=ZERO,
            total_ttc=total_ht,
            source_text=source,
            confidence=confidence,
        )
