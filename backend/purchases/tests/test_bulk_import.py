from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from companies.models import Company
from documents.paperless_api import PaperlessDocument
from purchases.models import InvoiceNature, PurchaseInvoice, Supplier
from purchases.services import PurchaseInvoiceImportService, find_matching_supplier


GOODS_TEXT = """FACTURE N° 1171/2025
DATE : 22/10/2025
CLIENT : DELIGHT EVENT MANAGEMENT ICE : 001443716000088
CALICE FLUTE 13 oz 114 48,60 5 540,40
Bouffat 70 cm U 30 140.00 4200,00
BON DE LIVRAISON N° 2025
TOTAL HT 9 740,40
TVA 20% 1 948,08
TOTAL TTC 11 688,48
VERRERIE ATLAS SARL ICE : 000216716000096
"""

SERVICE_TEXT = """Facture N° 26-0067
Date de la facture 24/05/2026
CLIENT : DELIGHT EVENT MANAGEMENT ICE : 001443716000088
PRESTATION TECHNIQUE 66 540,00
Montage et démontage, transport et déplacement
TOTAL HT 66 540,00 MAD
TVA20% 13 308,00 MAD
TOTAL TTC 79 848,00 MAD
AV EVENTS SARL ICE : 002887911000047
"""


def paperless_document(document_id, content, title="1-10-2025"):
    return PaperlessDocument(
        id=document_id,
        title=title,
        original_filename=f"{title}.pdf",
        created="2025-10-22",
        page_count=1,
        web_url=f"https://archive.example/documents/{document_id}/details",
        content=content,
    )


class SupplierMatchingTests(TestCase):
    def test_supplier_is_found_when_ocr_misreads_one_digit_of_the_ice(self):
        company = Company.objects.create(code="DEL", name="Delight")
        supplier = Supplier.objects.create(
            company=company, name="EKIPEXPO", ice="003253395000080"
        )

        found = find_matching_supplier(
            company=company, name="", ice="003253395000089"
        )

        self.assertEqual(found, supplier)


class NatureFilteringTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="DELIGHT",
            name="DELIGHT EVENT MANAGEMENT",
            ice="001443716000088",
        )
        self.client_mock = Mock()

    def service(self):
        return PurchaseInvoiceImportService(client=self.client_mock)

    def test_goods_invoice_is_imported_with_supplier_ice_and_lines(self):
        invoice, created = self.service().import_document(
            company=self.company,
            paperless_document=paperless_document(1, GOODS_TEXT, "89-10-2025"),
            allowed_natures={InvoiceNature.GOODS},
        )

        self.assertTrue(created)
        self.assertEqual(invoice.nature, InvoiceNature.GOODS)
        self.assertEqual(invoice.supplier_ice_raw, "000216716000096")
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(str(invoice.total_ttc), "11688.48")

    def test_service_invoice_is_not_imported_when_only_goods_are_allowed(self):
        invoice, created = self.service().import_document(
            company=self.company,
            paperless_document=paperless_document(2, SERVICE_TEXT),
            allowed_natures={InvoiceNature.GOODS},
        )

        self.assertIsNone(invoice)
        self.assertFalse(created)
        self.assertFalse(PurchaseInvoice.objects.exists())

    def test_supplier_default_nature_overrides_the_ocr_guess(self):
        Supplier.objects.create(
            company=self.company,
            name="AV EVENTS",
            ice="002887911000047",
            default_nature=InvoiceNature.GOODS,
        )

        invoice, created = self.service().import_document(
            company=self.company,
            paperless_document=paperless_document(3, SERVICE_TEXT),
            allowed_natures={InvoiceNature.GOODS},
        )

        self.assertTrue(created)
        self.assertEqual(invoice.nature, InvoiceNature.GOODS)
        self.assertIn("Nature imposée par le fournisseur", invoice.extraction_notes)


class BulkImportCommandTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="DELIGHT",
            name="DELIGHT EVENT MANAGEMENT",
            ice="001443716000088",
        )
        self.documents = [
            paperless_document(10, GOODS_TEXT, "89-10-2025"),
            paperless_document(11, SERVICE_TEXT, "15-5-2026"),
        ]

    def run_command(self, *args):
        client = Mock()
        client.iter_documents.return_value = iter(self.documents)
        output = StringIO()
        with patch(
            "purchases.management.commands.import_purchase_invoices.PaperlessApiClient",
            return_value=client,
        ), patch("purchases.services.PaperlessApiClient", return_value=client):
            call_command("import_purchase_invoices", "--company", "DELIGHT", *args, stdout=output)
        return output.getvalue()

    def test_dry_run_counts_without_saving(self):
        output = self.run_command("--dry-run")

        self.assertIn("SIMULATION", output)
        self.assertIn("à importer : 1", output)
        self.assertIn("ignorées (autre nature) : 1", output)
        self.assertFalse(PurchaseInvoice.objects.exists())

    def test_only_goods_invoices_are_imported_and_rerun_is_idempotent(self):
        self.run_command()
        self.documents = [
            paperless_document(10, GOODS_TEXT, "89-10-2025"),
            paperless_document(11, SERVICE_TEXT, "15-5-2026"),
        ]
        output = self.run_command()

        self.assertEqual(
            list(PurchaseInvoice.objects.values_list("paperless_document_id", flat=True)),
            [10],
        )
        self.assertIn("déjà importées : 1", output)


class OutOfRangeValuesTests(TestCase):
    """Un numéro lu comme un prix ne doit jamais interrompre l'import (débordement PostgreSQL)."""

    def setUp(self):
        self.company = Company.objects.create(
            code="DELIGHT", name="DELIGHT EVENT MANAGEMENT", ice="001443716000088"
        )

    def test_reference_numbers_are_not_read_as_prices(self):
        from purchases.extraction import parse_item_line

        self.assertIsNone(parse_item_line("RIB 1 007450000098700000403768 007450000098700000403768"))
        self.assertIsNone(parse_item_line("ARTICLE TEST 2 202600002873000 405200005746000"))

    def test_aberrant_line_is_skipped_and_invoice_is_imported(self):
        from purchases.extraction import ExtractedInvoiceLine, ExtractedPurchaseInvoice

        huge = Decimal("202600002873000")
        extractor = Mock()
        extractor.extract.return_value = ExtractedPurchaseInvoice(
            supplier_name="", supplier_ice="", invoice_number="X", invoice_date=None,
            due_date=None, currency="MAD", net_ht=Decimal("99999999999999999"), tax_amount=None,
            total_ttc=Decimal("120"),
            lines=(
                ExtractedInvoiceLine("Article normal", Decimal("1"), Decimal("100"), Decimal("100"),
                                     Decimal("20"), Decimal("20"), Decimal("120"), "src", Decimal("85")),
                ExtractedInvoiceLine("Numéro lu comme prix", Decimal("2"), huge, huge * 2,
                                     Decimal("20"), Decimal("0"), huge * 2, "src", Decimal("85")),
            ),
            confidence=Decimal("50"), notes="", nature="MARCHANDISES",
        )
        service = PurchaseInvoiceImportService(client=Mock(), extractor=extractor)

        invoice, created = service.import_document(
            company=self.company,
            paperless_document=paperless_document(1, "texte"),
        )

        self.assertTrue(created)
        self.assertIsNone(invoice.net_ht)
        self.assertEqual(list(invoice.lines.values_list("description", flat=True)), ["Article normal"])

    def test_one_failing_document_does_not_stop_the_import(self):
        from django.db import DataError

        documents = [
            paperless_document(10, GOODS_TEXT, "89-10-2025"),
            paperless_document(11, GOODS_TEXT.replace("1171/2025", "1172/2025"), "90-10-2025"),
        ]
        client = Mock()
        client.iter_documents.return_value = iter(documents)
        original = PurchaseInvoiceImportService.import_document

        def failing_once(service, **kwargs):
            if kwargs["paperless_document"].id == 10:
                raise DataError("numeric field overflow")
            return original(service, **kwargs)

        output, errors = StringIO(), StringIO()
        with patch(
            "purchases.management.commands.import_purchase_invoices.PaperlessApiClient",
            return_value=client,
        ), patch.object(PurchaseInvoiceImportService, "import_document", failing_once):
            call_command("import_purchase_invoices", "--company", "DELIGHT", stdout=output, stderr=errors)

        self.assertEqual(list(PurchaseInvoice.objects.values_list("paperless_document_id", flat=True)), [11])
        self.assertIn("en erreur (non importées) : 1", output.getvalue())
        self.assertIn("#10", errors.getvalue())
