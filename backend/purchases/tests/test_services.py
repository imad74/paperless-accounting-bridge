from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from django.test import TestCase, override_settings

from companies.models import Company
from documents.paperless_api import PaperlessDocument
from purchases.extraction import ExtractedInvoiceLine, ExtractedPurchaseInvoice
from purchases.models import (
    PurchaseInvoice,
    PurchaseInvoiceAnalysisJob,
    PurchaseInvoiceLine,
    Supplier,
)
from purchases.services import PurchaseInvoiceImportService, apply_ai_extraction


class PurchaseInvoiceImportServiceTests(TestCase):
    def test_import_creates_review_record_and_lines_only_once(self):
        company = Company.objects.create(code="IMP", name="Import")
        supplier = Supplier.objects.create(
            company=company,
            name="EVENT PRINT",
            ice="001 234 567 890 123",
        )
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
            supplier_name="EVENT PRINT",
            supplier_ice="001234567890123",
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
            purchase_order_number="BC-99",
            supplier_address="Zone industrielle, Marrakech",
            supplier_if="12345678",
            supplier_tp="87654321",
            supplier_rc="99887",
            buyer_name="Import",
            buyer_tax_id="009999999999999",
            subtotal_ht=Decimal("125"),
            discount_amount=Decimal("5"),
            shipping_amount=Decimal("0"),
            amount_due=Decimal("144"),
            payment_method="Virement",
            payment_terms="30 jours",
            supplier_iban="MA64011519000001205000534921",
        )
        service = PurchaseInvoiceImportService(client=client, extractor=extractor)

        invoice, created = service.import_document(company=company, paperless_document_id=7890)
        duplicate, duplicate_created = service.import_document(company=company, paperless_document_id=7890)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(invoice.pk, duplicate.pk)
        self.assertEqual(invoice.status, PurchaseInvoice.Status.TO_REVIEW)
        self.assertEqual(invoice.supplier, supplier)
        self.assertEqual(invoice.supplier_name_raw, "EVENT PRINT")
        self.assertEqual(invoice.supplier_ice_raw, "001234567890123")
        self.assertEqual(invoice.purchase_order_number, "BC-99")
        self.assertEqual(invoice.supplier_address_raw, "Zone industrielle, Marrakech")
        self.assertEqual(invoice.supplier_if_raw, "12345678")
        self.assertEqual(invoice.supplier_tp_raw, "87654321")
        self.assertEqual(invoice.supplier_rc_raw, "99887")
        self.assertEqual(invoice.buyer_name_raw, "Import")
        self.assertEqual(invoice.subtotal_ht, Decimal("125"))
        self.assertEqual(invoice.discount_amount, Decimal("5"))
        self.assertEqual(invoice.amount_due, Decimal("144"))
        self.assertEqual(invoice.payment_method, "Virement")
        self.assertEqual(invoice.raw_ocr_text, "Texte OCR")
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.tax_summaries.count(), 1)
        self.assertEqual(invoice.tax_summaries.get().taxable_amount, Decimal("120"))
        client.get_document.assert_called_once_with(7890)

    def test_ai_result_replaces_fields_and_lines_for_human_review(self):
        company = Company.objects.create(code="AI", name="Acheteur IA")
        invoice = PurchaseInvoice.objects.create(
            company=company,
            paperless_document_id=91,
            invoice_number="ancien",
            status=PurchaseInvoice.Status.VALIDATED,
        )
        PurchaseInvoiceLine.objects.create(
            invoice=invoice,
            position=1,
            description="ancienne ligne",
        )
        extracted = ExtractedPurchaseInvoice(
            supplier_name="NOUVEAU FOURNISSEUR",
            supplier_ice="001234567890123",
            invoice_number="F-2026-91",
            invoice_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            currency="MAD",
            net_ht=Decimal("100"),
            tax_amount=Decimal("20"),
            total_ttc=Decimal("120"),
            lines=(ExtractedInvoiceLine(
                description="Article IA",
                quantity=Decimal("2"),
                unit_price_ht=Decimal("50"),
                total_ht=Decimal("100"),
                tax_rate=Decimal("20"),
                tax_amount=Decimal("20"),
                total_ttc=Decimal("120"),
                source_text="(lu par l’IA)",
                confidence=Decimal("90"),
            ),),
            confidence=Decimal("90"),
            notes="Extraction IA.",
            purchase_order_number="BC-91",
            supplier_if="12345678",
            supplier_tp="87654321",
            supplier_rc="99887",
            delivery_address="Entrepôt",
            amount_due=Decimal("120"),
        )

        apply_ai_extraction(invoice, extracted)

        invoice.refresh_from_db()
        self.assertEqual(invoice.extraction_method, PurchaseInvoice.ExtractionMethod.AI_PDF)
        self.assertEqual(invoice.status, PurchaseInvoice.Status.TO_REVIEW)
        self.assertEqual(invoice.invoice_number, "F-2026-91")
        self.assertEqual(invoice.purchase_order_number, "BC-91")
        self.assertEqual(invoice.supplier_if_raw, "12345678")
        self.assertEqual(invoice.supplier_tp_raw, "87654321")
        self.assertEqual(invoice.supplier_rc_raw, "99887")
        self.assertEqual(invoice.delivery_address_raw, "Entrepôt")
        self.assertEqual(invoice.lines.get().description, "Article IA")

    @override_settings(PURCHASES_AI_ENABLED=True, PURCHASES_AI_AUTO_PROCESS=True)
    def test_ai_result_is_integrated_automatically(self):
        company = Company.objects.create(code="AUTO", name="Acheteur automatique")
        invoice = PurchaseInvoice.objects.create(
            company=company,
            paperless_document_id=92,
        )
        extracted = ExtractedPurchaseInvoice(
            supplier_name="FOURNISSEUR AUTOMATIQUE",
            supplier_ice="001234567890123",
            invoice_number="AUTO-92",
            invoice_date=date(2026, 11, 2),
            due_date=None,
            currency="MAD",
            net_ht=Decimal("100"),
            tax_amount=Decimal("20"),
            total_ttc=Decimal("120"),
            lines=(
                ExtractedInvoiceLine(
                    description="Article intégré",
                    quantity=Decimal("1"),
                    unit_price_ht=Decimal("100"),
                    total_ht=Decimal("100"),
                    tax_rate=Decimal("20"),
                    tax_amount=Decimal("20"),
                    total_ttc=Decimal("120"),
                    source_text="(lu par l’IA)",
                    confidence=Decimal("92"),
                ),
            ),
            confidence=Decimal("92"),
            notes="Extraction cohérente.",
            supplier_address="Marrakech",
            supplier_if="12345678",
            supplier_tp="87654321",
            supplier_rc="99887",
        )

        apply_ai_extraction(invoice, extracted)

        invoice.refresh_from_db()
        line = invoice.lines.get()
        self.assertEqual(invoice.status, PurchaseInvoice.Status.VALIDATED)
        self.assertIsNotNone(invoice.validated_at)
        self.assertIsNone(invoice.validated_by)
        self.assertTrue(line.verified)
        self.assertEqual(invoice.supplier.name, "FOURNISSEUR AUTOMATIQUE")
        self.assertEqual(invoice.supplier.ice, "001234567890123")
        self.assertEqual(invoice.supplier.if_number, "12345678")
        self.assertIn("Intégrée automatiquement", invoice.extraction_notes)

    @override_settings(
        PURCHASES_AI_ENABLED=True,
        PURCHASES_AI_AUTO_PROCESS=True,
        PURCHASES_EXTRACTION_ENGINE="rules",
    )
    def test_rule_import_queues_automatic_ai_analysis(self):
        company = Company.objects.create(code="QUEUE", name="Import automatique")
        document = PaperlessDocument(
            id=7900,
            title="Facture à analyser",
            original_filename="facture.pdf",
            created="2026-11-02",
            page_count=1,
            web_url="https://archive.example/documents/7900/details",
            content="Texte OCR",
        )
        extractor = Mock()
        extractor.extract.return_value = ExtractedPurchaseInvoice(
            supplier_name="FOURNISSEUR FILE",
            supplier_ice="",
            invoice_number="Q-7900",
            invoice_date=date(2026, 11, 2),
            due_date=None,
            currency="MAD",
            net_ht=Decimal("10"),
            tax_amount=Decimal("2"),
            total_ttc=Decimal("12"),
            lines=(),
            confidence=Decimal("50"),
            notes="OCR provisoire.",
        )

        invoice, created = PurchaseInvoiceImportService(
            client=Mock(), extractor=extractor
        ).import_document(company=company, paperless_document=document)

        self.assertTrue(created)
        self.assertEqual(invoice.status, PurchaseInvoice.Status.TO_REVIEW)
        job = PurchaseInvoiceAnalysisJob.objects.get(invoice=invoice)
        self.assertEqual(job.status, PurchaseInvoiceAnalysisJob.Status.PENDING)
