from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from django.test import TestCase

from companies.models import Company
from documents.paperless_api import PaperlessDocument
from purchases.extraction import ExtractedInvoiceLine, ExtractedPurchaseInvoice
from purchases.models import PurchaseInvoice
from purchases.services import PurchaseInvoiceImportService


class PurchaseInvoiceImportServiceTests(TestCase):
    def test_import_creates_review_record_and_lines_only_once(self):
        company = Company.objects.create(code="IMP", name="Import")
        client = Mock()
        client.get_document.return_value = PaperlessDocument(
            id=7890,
            title="128-3-2023 FACTURE",
            original_filename="128-3-2023 FACTURE.pdf",
            created="2023-03-13",
            page_count=1,
            web_url="https://archive.example/documents/7890/details",
            content="Texte OCR",
        )
        extractor = Mock()
        extractor.extract.return_value = ExtractedPurchaseInvoice(
            invoice_number="FA2200883",
            invoice_date=date(2023, 3, 13),
            due_date=None,
            currency="MAD",
            net_ht=Decimal("120"),
            tax_amount=Decimal("24"),
            total_ttc=Decimal("144"),
            lines=(
                ExtractedInvoiceLine(
                    description="Découpe vinyle",
                    quantity=Decimal("6"),
                    unit_price_ht=Decimal("20"),
                    total_ht=Decimal("120"),
                    tax_rate=Decimal("0"),
                    tax_amount=Decimal("0"),
                    total_ttc=Decimal("120"),
                    source_text="6 Découpe vinyle 20,00 120,00",
                    confidence=Decimal("78"),
                ),
            ),
            confidence=Decimal("70"),
            notes="À vérifier.",
        )
        service = PurchaseInvoiceImportService(client=client, extractor=extractor)

        invoice, created = service.import_document(company=company, paperless_document_id=7890)
        duplicate, duplicate_created = service.import_document(company=company, paperless_document_id=7890)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(invoice.pk, duplicate.pk)
        self.assertEqual(invoice.status, PurchaseInvoice.Status.TO_REVIEW)
        self.assertEqual(invoice.raw_ocr_text, "Texte OCR")
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.tax_summaries.count(), 1)
        self.assertEqual(invoice.tax_summaries.get().taxable_amount, Decimal("120"))
        client.get_document.assert_called_once_with(7890)
