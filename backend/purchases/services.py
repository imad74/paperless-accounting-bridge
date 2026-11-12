from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from documents.models import Document
from documents.paperless_api import PaperlessApiClient

from .extraction import PurchaseInvoiceExtractor, ice_digits, is_same_ice
from .models import (
    InvoiceNature,
    PurchaseInvoice,
    PurchaseInvoiceAnalysisJob,
    PurchaseInvoiceLine,
    PurchaseInvoiceTaxSummary,
    Supplier,
)


SUPPLIER_EVIDENCE_MIN_DOCUMENTS = 3
# Capacité des colonnes (DecimalField max_digits=15) : 10^11 avec 4 décimales, 10^13 avec 2.
_LIMIT_4_DECIMALS = Decimal("99999999999")
_LIMIT_2_DECIMALS = Decimal("9999999999999")


def plausible_amount(value):
    """Montant d'en-tête lu par l'OCR, ou None s'il est aberrant."""
    if value is None:
        return None
    try:
        return value if abs(value) <= _LIMIT_2_DECIMALS else None
    except (TypeError, InvalidOperation):
        return None


def plausible_nonnegative_amount(value):
    value = plausible_amount(value)
    return value if value is not None and value >= 0 else None


def line_fits_database(line):
    """Écarte une ligne OCR aberrante plutôt que d'interrompre l'import."""
    try:
        return (
            abs(line.quantity) <= _LIMIT_4_DECIMALS
            and abs(line.unit_price_ht) <= _LIMIT_4_DECIMALS
            and all(
                abs(value) <= _LIMIT_2_DECIMALS
                for value in (line.total_ht, line.tax_amount, line.total_ttc)
            )
            and 0 <= line.tax_rate <= 100
            and 0 <= getattr(line, "discount_percent", 0) <= 100
        )
    except (TypeError, InvalidOperation):
        return False


def extractor_for_company(company):
    """Extracteur qui ignore l'ICE, le nom et le compte bancaire de la société acheteuse."""
    return PurchaseInvoiceExtractor(
        excluded_ices=[company.ice] if getattr(company, "ice", "") else [],
        excluded_names=[company.name] if getattr(company, "name", "") else [],
        own_bank_accounts=getattr(settings, "PURCHASES_OWN_BANK_ACCOUNTS", ()),
    )


def ai_extractor_for_company(company):
    """Extracteur visuel du PDF, chargé à la demande pour garder l'IA facultative."""
    from .ai_extraction import OllamaInvoiceExtractor

    return OllamaInvoiceExtractor(
        excluded_ices=[company.ice] if getattr(company, "ice", "") else [],
        excluded_names=[company.name] if getattr(company, "name", "") else [],
    )


def rebuild_tax_summaries(invoice):
    summaries = invoice.lines.values("tax_rate").annotate(
        taxable_amount=Sum("total_ht"),
        tax_amount=Sum("tax_amount"),
    )
    invoice.tax_summaries.all().delete()
    PurchaseInvoiceTaxSummary.objects.bulk_create(
        PurchaseInvoiceTaxSummary(
            invoice=invoice,
            tax_rate=summary["tax_rate"],
            taxable_amount=summary["taxable_amount"],
            tax_amount=summary["tax_amount"],
        )
        for summary in summaries
    )


def find_matching_supplier(*, company, name, ice):
    suppliers = Supplier.objects.filter(company=company)
    if ice:
        candidates = [s for s in suppliers.exclude(ice="") if len(ice_digits(s.ice)) == 15]
        for supplier in candidates:
            if ice_digits(supplier.ice) == ice:
                return supplier
        # Lecture OCR à un chiffre près.
        for supplier in candidates:
            if is_same_ice(supplier.ice, ice):
                return supplier
    if name:
        return suppliers.filter(
            normalized_name=Supplier.normalize_name(name)
        ).first()
    return None


@transaction.atomic
def link_invoices_to_suppliers(company):
    """Rattache à leur fournisseur les factures importées sans fournisseur,
    d'après l'ICE lu sur la facture (à un chiffre près). Renvoie le nombre rattaché."""
    suppliers = [
        (ice_digits(supplier.ice), supplier)
        for supplier in Supplier.objects.filter(company=company).exclude(ice="")
        if len(ice_digits(supplier.ice)) == 15
    ]
    exact = {ice: supplier for ice, supplier in suppliers}
    linked = 0
    invoices = PurchaseInvoice.objects.select_for_update().filter(
        company=company, supplier__isnull=True
    ).exclude(supplier_ice_raw="")
    for invoice in invoices:
        ice = ice_digits(invoice.supplier_ice_raw)
        supplier = exact.get(ice) or next(
            (candidate for known, candidate in suppliers if is_same_ice(known, ice)), None
        )
        if supplier:
            invoice.supplier = supplier
            invoice.save(update_fields=["supplier", "updated_at"])
            linked += 1
    return linked


@transaction.atomic
def refresh_supplier_identity(invoice, *, extractor=None):
    extractor = extractor or extractor_for_company(invoice.company)
    supplier_name, supplier_ice, ambiguous_ice = (
        extractor.extract_supplier_identity(invoice.raw_ocr_text)
    )
    changed_fields = []
    if supplier_name and not invoice.supplier_name_raw:
        invoice.supplier_name_raw = supplier_name
        changed_fields.append("supplier_name_raw")
    if supplier_ice and not invoice.supplier_ice_raw:
        invoice.supplier_ice_raw = supplier_ice
        changed_fields.append("supplier_ice_raw")
    if not invoice.supplier_id:
        supplier = find_matching_supplier(
            company=invoice.company,
            name=invoice.supplier_name_raw or supplier_name,
            ice=invoice.supplier_ice_raw or supplier_ice,
        )
        if supplier:
            invoice.supplier = supplier
            changed_fields.append("supplier")
    if changed_fields:
        invoice.status = PurchaseInvoice.Status.TO_REVIEW
        invoice.validated_by = None
        invoice.validated_at = None
        changed_fields.extend(
            ("status", "validated_by", "validated_at", "updated_at")
        )
        invoice.save(update_fields=changed_fields)
    return bool(changed_fields), ambiguous_ice


class PurchaseInvoiceImportService:
    def __init__(self, *, client=None, extractor=None):
        self.client = client or PaperlessApiClient()
        self.extractor = extractor

    def _extractor(self, company):
        return self.extractor or extractor_for_company(company)

    def analyse(self, *, company, paperless_document):
        """Extraction sans enregistrement : renvoie (données extraites, fournisseur, nature)."""
        if (
            self.extractor is None
            and getattr(settings, "PURCHASES_AI_ENABLED", False)
            and getattr(settings, "PURCHASES_EXTRACTION_ENGINE", "rules") == "ollama"
        ):
            extracted = ai_extractor_for_company(company).extract_document(
                pdf_bytes=self.client.download_pdf(paperless_document.id),
                text=paperless_document.content,
                title=paperless_document.title,
                page_count=paperless_document.page_count,
            ).extracted
        else:
            extracted = self._extractor(company).extract(
                paperless_document.content,
                title=paperless_document.title,
            )
        supplier = find_matching_supplier(
            company=company,
            name=extracted.supplier_name,
            ice=extracted.supplier_ice,
        )
        nature = getattr(extracted, "nature", InvoiceNature.UNKNOWN) or InvoiceNature.UNKNOWN
        if supplier and supplier.default_nature:
            nature = supplier.default_nature
        elif (
            supplier
            and nature == InvoiceNature.UNKNOWN
            and supplier.detected_nature not in ("", InvoiceNature.UNKNOWN, InvoiceNature.SALE)
            and supplier.paperless_document_count >= SUPPLIER_EVIDENCE_MIN_DOCUMENTS
        ):
            # Facture illisible d'un fournisseur bien connu : on reprend sa nature habituelle.
            nature = supplier.detected_nature
        if nature not in InvoiceNature.values:
            nature = InvoiceNature.UNKNOWN
        return extracted, supplier, nature

    @transaction.atomic
    def import_document(
        self,
        *,
        company,
        paperless_document_id=None,
        paperless_document=None,
        allowed_natures=None,
    ):
        """Importe une facture Paperless.

        Renvoie (facture, créée). Avec `allowed_natures`, une facture d'une autre
        nature n'est pas enregistrée : (None, False).
        """
        document_id = paperless_document.id if paperless_document else paperless_document_id
        existing = PurchaseInvoice.objects.filter(
            company=company,
            paperless_document_id=document_id,
        ).first()
        if existing:
            return existing, False

        if paperless_document is None:
            paperless_document = self.client.get_document(paperless_document_id)
        extracted, supplier, nature = self.analyse(
            company=company, paperless_document=paperless_document
        )
        if allowed_natures is not None and nature not in allowed_natures:
            return None, False

        pab_document = Document.objects.filter(
            company=company,
            paperless_id=paperless_document.id,
        ).first()
        notes = extracted.notes
        if supplier and supplier.default_nature:
            notes += f" Nature imposée par le fournisseur : {supplier.get_default_nature_display()}."
        elif supplier and nature != extracted.nature:
            notes += f" Nature reprise de l’annuaire fournisseurs : {supplier.get_detected_nature_display()}."
        invoice = PurchaseInvoice.objects.create(
            company=company,
            supplier=supplier,
            supplier_name_raw=extracted.supplier_name,
            supplier_ice_raw=extracted.supplier_ice,
            document=pab_document,
            paperless_document_id=paperless_document.id,
            paperless_title=paperless_document.title,
            original_filename=paperless_document.original_filename,
            invoice_number=extracted.invoice_number,
            purchase_order_number=extracted.purchase_order_number,
            invoice_date=extracted.invoice_date,
            due_date=extracted.due_date
            if not (extracted.due_date and extracted.invoice_date and extracted.due_date < extracted.invoice_date)
            else None,
            currency=extracted.currency,
            supplier_address_raw=extracted.supplier_address,
            supplier_contact_raw=extracted.supplier_contact,
            supplier_if_raw=extracted.supplier_if,
            supplier_rc_raw=extracted.supplier_rc,
            buyer_name_raw=extracted.buyer_name,
            buyer_tax_id_raw=extracted.buyer_tax_id,
            billing_address_raw=extracted.billing_address,
            delivery_address_raw=extracted.delivery_address,
            subtotal_ht=plausible_amount(extracted.subtotal_ht),
            discount_amount=plausible_nonnegative_amount(extracted.discount_amount) or Decimal("0"),
            shipping_amount=plausible_nonnegative_amount(extracted.shipping_amount) or Decimal("0"),
            net_ht=plausible_amount(extracted.net_ht),
            tax_amount=plausible_amount(extracted.tax_amount),
            total_ttc=plausible_amount(extracted.total_ttc),
            amount_due=plausible_amount(extracted.amount_due),
            payment_method=extracted.payment_method,
            payment_terms=extracted.payment_terms,
            supplier_iban=extracted.supplier_iban,
            supplier_swift=extracted.supplier_swift,
            nature=nature,
            status=PurchaseInvoice.Status.TO_REVIEW,
            extraction_method=PurchaseInvoice.ExtractionMethod.PAPERLESS_OCR,
            extraction_confidence=extracted.confidence,
            raw_ocr_text=paperless_document.content,
            extraction_notes=notes,
        )
        PurchaseInvoiceLine.objects.bulk_create(
            PurchaseInvoiceLine(
                invoice=invoice,
                position=position,
                reference=getattr(line, "reference", ""),
                description=line.description,
                quantity=line.quantity,
                unit=getattr(line, "unit", ""),
                unit_price_ht=line.unit_price_ht,
                discount_percent=getattr(line, "discount_percent", 0),
                tax_rate=line.tax_rate,
                total_ht=line.total_ht,
                tax_amount=line.tax_amount,
                total_ttc=line.total_ttc,
                source_text=line.source_text,
                extraction_confidence=line.confidence,
            )
            for position, line in enumerate(
                (line for line in extracted.lines if line_fits_database(line)), start=1
            )
        )
        rebuild_tax_summaries(invoice)
        return invoice, True


def _invoice_values_from_extraction(extracted):
    return {
        "supplier_name_raw": extracted.supplier_name,
        "supplier_ice_raw": extracted.supplier_ice,
        "invoice_number": extracted.invoice_number,
        "purchase_order_number": extracted.purchase_order_number,
        "invoice_date": extracted.invoice_date,
        "due_date": (
            extracted.due_date
            if not (
                extracted.due_date
                and extracted.invoice_date
                and extracted.due_date < extracted.invoice_date
            )
            else None
        ),
        "currency": extracted.currency,
        "supplier_address_raw": extracted.supplier_address,
        "supplier_contact_raw": extracted.supplier_contact,
        "supplier_if_raw": extracted.supplier_if,
        "supplier_rc_raw": extracted.supplier_rc,
        "buyer_name_raw": extracted.buyer_name,
        "buyer_tax_id_raw": extracted.buyer_tax_id,
        "billing_address_raw": extracted.billing_address,
        "delivery_address_raw": extracted.delivery_address,
        "subtotal_ht": plausible_amount(extracted.subtotal_ht),
        "discount_amount": plausible_nonnegative_amount(extracted.discount_amount) or Decimal("0"),
        "shipping_amount": plausible_nonnegative_amount(extracted.shipping_amount) or Decimal("0"),
        "net_ht": plausible_amount(extracted.net_ht),
        "tax_amount": plausible_amount(extracted.tax_amount),
        "total_ttc": plausible_amount(extracted.total_ttc),
        "amount_due": plausible_amount(extracted.amount_due),
        "payment_method": extracted.payment_method,
        "payment_terms": extracted.payment_terms,
        "supplier_iban": extracted.supplier_iban,
        "supplier_swift": extracted.supplier_swift,
        "nature": extracted.nature if extracted.nature in InvoiceNature.values else InvoiceNature.UNKNOWN,
        "extraction_confidence": extracted.confidence,
        "extraction_notes": extracted.notes,
    }


@transaction.atomic
def apply_ai_extraction(invoice, extracted):
    """Remplace les champs OCR et les lignes par un résultat IA à contrôler."""
    supplier = find_matching_supplier(
        company=invoice.company,
        name=extracted.supplier_name,
        ice=extracted.supplier_ice,
    )
    for field, value in _invoice_values_from_extraction(extracted).items():
        setattr(invoice, field, value)
    invoice.supplier = supplier
    invoice.extraction_method = PurchaseInvoice.ExtractionMethod.AI_PDF
    invoice.status = PurchaseInvoice.Status.TO_REVIEW
    invoice.validated_by = None
    invoice.validated_at = None
    invoice.save()
    invoice.lines.all().delete()
    PurchaseInvoiceLine.objects.bulk_create(
        PurchaseInvoiceLine(
            invoice=invoice,
            position=position,
            reference=getattr(line, "reference", ""),
            description=line.description,
            quantity=line.quantity,
            unit=getattr(line, "unit", ""),
            unit_price_ht=line.unit_price_ht,
            discount_percent=getattr(line, "discount_percent", 0),
            tax_rate=line.tax_rate,
            total_ht=line.total_ht,
            tax_amount=line.tax_amount,
            total_ttc=line.total_ttc,
            source_text=line.source_text,
            extraction_confidence=line.confidence,
        )
        for position, line in enumerate(
            (line for line in extracted.lines if line_fits_database(line)), start=1
        )
    )
    rebuild_tax_summaries(invoice)
    return invoice


def reanalyze_invoice_with_ai(invoice, *, client=None, extractor=None):
    """Relit le PDF Paperless par IA puis remet la facture en validation humaine."""
    if not invoice.paperless_document_id:
        from .ai_extraction import AiExtractionError

        raise AiExtractionError("Cette facture n’est pas liée à un document Paperless.")
    client = client or PaperlessApiClient()
    document = client.get_document(invoice.paperless_document_id)
    extractor = extractor or ai_extractor_for_company(invoice.company)
    result = extractor.extract_document(
        pdf_bytes=client.download_pdf(document.id),
        text=document.content,
        title=document.title,
        page_count=document.page_count,
    )
    apply_ai_extraction(invoice, result.extracted)
    return result


@transaction.atomic
def queue_ai_analysis(invoice, *, requested_by=None):
    """Place une facture dans la file locale, sans bloquer la requête web."""
    if not getattr(settings, "PURCHASES_AI_ENABLED", False):
        from .ai_extraction import AiExtractionError

        raise AiExtractionError("L’analyse IA locale n’est pas activée.")
    if not invoice.paperless_document_id:
        from .ai_extraction import AiExtractionError

        raise AiExtractionError("Cette facture n’est pas liée à un document Paperless.")
    job, _created = PurchaseInvoiceAnalysisJob.objects.update_or_create(
        invoice=invoice,
        defaults={
            "status": PurchaseInvoiceAnalysisJob.Status.PENDING,
            "requested_by": requested_by,
            "model_name": getattr(settings, "OLLAMA_MODEL", "qwen2.5vl:3b"),
            "error_message": "",
            "started_at": None,
            "finished_at": None,
        },
    )
    return job
