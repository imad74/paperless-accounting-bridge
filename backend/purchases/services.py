from django.db import transaction
from django.db.models import Sum

from documents.models import Document
from documents.paperless_api import PaperlessApiClient

from .extraction import PurchaseInvoiceExtractor
from .models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseInvoiceTaxSummary,
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


class PurchaseInvoiceImportService:
    def __init__(self, *, client=None, extractor=None):
        self.client = client or PaperlessApiClient()
        self.extractor = extractor or PurchaseInvoiceExtractor()

    @transaction.atomic
    def import_document(self, *, company, paperless_document_id):
        existing = PurchaseInvoice.objects.filter(
            company=company,
            paperless_document_id=paperless_document_id,
        ).first()
        if existing:
            return existing, False

        paperless_document = self.client.get_document(paperless_document_id)
        extracted = self.extractor.extract(paperless_document.content)
        pab_document = Document.objects.filter(
            company=company,
            paperless_id=paperless_document.id,
        ).first()
        invoice = PurchaseInvoice.objects.create(
            company=company,
            document=pab_document,
            paperless_document_id=paperless_document.id,
            paperless_title=paperless_document.title,
            original_filename=paperless_document.original_filename,
            invoice_number=extracted.invoice_number,
            invoice_date=extracted.invoice_date,
            due_date=extracted.due_date,
            currency=extracted.currency,
            net_ht=extracted.net_ht,
            tax_amount=extracted.tax_amount,
            total_ttc=extracted.total_ttc,
            status=PurchaseInvoice.Status.TO_REVIEW,
            extraction_method=PurchaseInvoice.ExtractionMethod.PAPERLESS_OCR,
            extraction_confidence=extracted.confidence,
            raw_ocr_text=paperless_document.content,
            extraction_notes=extracted.notes,
        )
        PurchaseInvoiceLine.objects.bulk_create(
            PurchaseInvoiceLine(
                invoice=invoice,
                position=position,
                description=line.description,
                quantity=line.quantity,
                unit_price_ht=line.unit_price_ht,
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
