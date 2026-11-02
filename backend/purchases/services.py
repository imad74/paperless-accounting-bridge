from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from documents.models import Document
from documents.paperless_api import PaperlessApiClient

from .extraction import PurchaseInvoiceExtractor, ice_digits, is_same_ice
from .models import (
    InvoiceNature,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseInvoiceTaxSummary,
    Supplier,
)


SUPPLIER_EVIDENCE_MIN_DOCUMENTS = 3


def extractor_for_company(company):
    """Extracteur qui ignore l'ICE, le nom et le compte bancaire de la société acheteuse."""
    return PurchaseInvoiceExtractor(
        excluded_ices=[company.ice] if getattr(company, "ice", "") else [],
        excluded_names=[company.name] if getattr(company, "name", "") else [],
        own_bank_accounts=getattr(settings, "PURCHASES_OWN_BANK_ACCOUNTS", ()),
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
            invoice_date=extracted.invoice_date,
            due_date=extracted.due_date
            if not (extracted.due_date and extracted.invoice_date and extracted.due_date < extracted.invoice_date)
            else None,
            currency=extracted.currency,
            net_ht=extracted.net_ht,
            tax_amount=extracted.tax_amount,
            total_ttc=extracted.total_ttc,
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
            for position, line in enumerate(extracted.lines, start=1)
        )
        rebuild_tax_summaries(invoice)
        return invoice, True
