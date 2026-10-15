from decimal import Decimal

from django.test import SimpleTestCase

from purchases.extraction import PurchaseInvoiceExtractor, parse_decimal


class PurchaseInvoiceExtractorTests(SimpleTestCase):
    def test_french_and_international_decimals_are_normalized(self):
        self.assertEqual(parse_decimal("2 053,38"), Decimal("2053.38"))
        self.assertEqual(parse_decimal("1700,00"), Decimal("1700.00"))
        self.assertEqual(parse_decimal("1,756.25"), Decimal("1756.25"))

    def test_extracts_header_totals_and_a_standard_item_line(self):
        text = """
        Facture Numéro. FA2200883 Date. 13/03/2023
        Quantité Désignation Prix Unit. HT Prix Total HT
        6 DECOUPE SUR VINYL BLANC 20,00 120,00
        Total HT 120,00
        Montant TVA 24,00
        Total TTC 144,00 MAD
        """

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.invoice_number, "FA2200883")
        self.assertEqual(result.invoice_date.isoformat(), "2023-03-13")
        self.assertEqual(result.currency, "MAD")
        self.assertEqual(result.net_ht, Decimal("120.00"))
        self.assertEqual(result.tax_amount, Decimal("24.00"))
        self.assertEqual(result.total_ttc, Decimal("144.00"))
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].description, "DECOUPE SUR VINYL BLANC")
        self.assertEqual(result.lines[0].quantity, Decimal("6"))
        self.assertEqual(result.lines[0].unit_price_ht, Decimal("20.00"))
        self.assertEqual(result.lines[0].total_ht, Decimal("120.00"))

    def test_extracts_repeated_service_lines_with_quantity_unit_price_total(self):
        text = """
        N° FACTURE : 2303-0000109
        Date : 28/02/2023
        Heures normales 95,00 21,61 2 053,38
        Indemnité de panier 0,50 551,52 275,76
        """

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.invoice_number, "2303-0000109")
        self.assertEqual(len(result.lines), 2)
        self.assertEqual(result.lines[0].description, "Heures normales")
        self.assertEqual(result.lines[0].quantity, Decimal("95.00"))
        self.assertEqual(result.lines[0].total_ht, Decimal("2053.38"))

    def test_uncertain_document_is_left_for_manual_review(self):
        result = PurchaseInvoiceExtractor().extract("Facture illisible")

        self.assertEqual(result.lines, ())
        self.assertIn("Aucune ligne", result.notes)
        self.assertLess(result.confidence, Decimal("50"))
