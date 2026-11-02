from decimal import Decimal

from django.test import SimpleTestCase

from purchases.extraction import (
    NATURE_EXPENSE,
    NATURE_GOODS,
    NATURE_RENTAL,
    NATURE_SALE,
    NATURE_SERVICE,
    PurchaseInvoiceExtractor,
    parse_decimal,
    parse_item_line,
)


class PurchaseInvoiceExtractorTests(SimpleTestCase):
    def test_french_and_international_decimals_are_normalized(self):
        self.assertEqual(parse_decimal("2 053,38"), Decimal("2053.38"))
        self.assertEqual(parse_decimal("1700,00"), Decimal("1700.00"))
        self.assertEqual(parse_decimal("1,756.25"), Decimal("1756.25"))

    def test_extracts_header_totals_and_a_standard_item_line(self):
        text = """
        Fournisseur : EVENT PRINT
        ICE : 001234567890123
        Facture Numéro. FA2200883 Date. 13/03/2023
        Quantité Désignation Prix Unit. HT Prix Total HT
        6 DECOUPE SUR VINYL BLANC 20,00 120,00
        Total HT 120,00
        Montant TVA 24,00
        Total TTC 144,00 MAD
        """

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.supplier_name, "EVENT PRINT")
        self.assertEqual(result.supplier_ice, "001234567890123")
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

    def test_company_name_can_be_read_from_the_ice_line(self):
        result = PurchaseInvoiceExtractor().extract(
            "EVENT PRINT ICE : 001234567890123\nTotal TTC 120,00 MAD"
        )

        self.assertEqual(result.supplier_name, "EVENT PRINT")
        self.assertEqual(result.supplier_ice, "001234567890123")

    def test_ice_announced_as_the_customer_is_not_the_supplier(self):
        result = PurchaseInvoiceExtractor().extract(
            "Fournisseur : ALPHA\n"
            "ICE : 001234567890123\n"
            "Client : DELIGHT EVENT ICE : 009876543210987"
        )

        self.assertEqual(result.supplier_name, "ALPHA")
        self.assertEqual(result.supplier_ice, "001234567890123")

    def test_multiple_ice_values_are_left_for_manual_selection(self):
        result = PurchaseInvoiceExtractor().extract(
            "Fournisseur : ALPHA\n"
            "ICE : 001234567890123\n"
            "ICE : 009876543210987"
        )

        self.assertEqual(result.supplier_name, "ALPHA")
        self.assertEqual(result.supplier_ice, "")
        self.assertIn("Plusieurs ICE", result.notes)


class SupplierIdentificationWithBuyerExclusionTests(SimpleTestCase):
    """L'ICE de la société acheteuse (et ses variantes OCR) n'est jamais proposé."""

    def extractor(self):
        return PurchaseInvoiceExtractor(
            excluded_ices=["001443716000088"],
            excluded_names=["DELIGHT EVENT MANAGEMENT"],
        )

    def test_buyer_ice_and_ocr_variants_are_ignored(self):
        text = (
            "Facture Numéro. FA2205395 Date. 15/04/2026\n"
            "Client. DELIGHT EVENT MANAGEMENT\n"
            "IGE, 001443716000088\n"
            "Code ICE 601443716000088 MARRAKECH\n"
            "EVENT PRINT SARL AU, au capital de 2.000.000,00 Dhs\n"
            "Taxe Prof. 64000394. IF. 14457565 » RC. 58971 + ICE. 000216716000096\n"
        )

        result = self.extractor().extract(text)

        self.assertEqual(result.supplier_ice, "000216716000096")
        self.assertNotIn("Plusieurs ICE", result.notes)
        self.assertNotIn("DELIGHT", result.supplier_name.upper())

    def test_ocr_spellings_of_ice_are_recognised(self):
        text = "KTI : S.A.R.L. au capital 24 000 000 Dhs - TP:35502667 - 1CE:001524292000052"

        name, ice, ambiguous = self.extractor().extract_supplier_identity(text)

        self.assertEqual(ice, "001524292000052")
        self.assertEqual(name, "KTI")
        self.assertFalse(ambiguous)

    def test_same_supplier_read_twice_with_one_wrong_digit_is_not_ambiguous(self):
        text = "ICE : 003253395000080\nPied de page ICE : 003253395000089"

        _name, ice, ambiguous = self.extractor().extract_supplier_identity(text)

        self.assertFalse(ambiguous)
        self.assertIn(ice, ("003253395000080", "003253395000089"))


class TotalsControlTests(SimpleTestCase):
    def test_totals_are_read_from_a_header_row(self):
        text = (
            "Total HT Montant TVA Total TTC Acompte NET À PAYER\n"
            "1 680,00 336,00 2 016,00 0,00 2 016,00 MAD\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.net_ht, Decimal("1680.00"))
        self.assertEqual(result.tax_amount, Decimal("336.00"))
        self.assertEqual(result.total_ttc, Decimal("2016.00"))
        self.assertEqual(result.tax_rate, Decimal("20"))
        self.assertIn("HT + TVA", result.notes)

    def test_amount_written_in_words_confirms_the_total(self):
        text = (
            "FACTURE Ng 290934\n"
            "PAYMENT 30 JOURS #4 326,00\n"
            "7 326,00 1 7 326,00\n"
            "Facture arrêtée à la somme de : sept mille trois cent vingt six Dirhams\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.total_ttc, Decimal("7326.00"))
        self.assertEqual(result.invoice_number, "290934")

    def test_amount_in_words_selects_the_right_invoice_in_a_bundle(self):
        text = (
            "Autre facture HT 190 840,00 TVA 38 168,00 TTC 229 008,00\n"
            "arrêtée à la somme de\n"
            "cent quatre-vingt dix-sept mille six cent dix-huit Dirhams et quarante centimes\n"
            "TVA % TVA Montant HT Montant TVA\n"
            "2 20,00 164682,00 32936,40\n"
            "Net 197 618,40\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.total_ttc, Decimal("197618.40"))
        self.assertEqual(result.net_ht, Decimal("164682.00"))

    def test_date_matching_the_document_month_is_preferred(self):
        text = "Séjour du 22/05/26 au 24/05/26\nCasablanca, le: 05/06/26\nFACTURE N° 12"

        result = PurchaseInvoiceExtractor().extract(text, title="79-6-2026")

        self.assertEqual(result.invoice_date.isoformat(), "2026-06-05")

    def test_lines_receive_the_invoice_tax_rate(self):
        text = (
            "6 DECOUPE SUR VINYL BLANC 20,00 120,00\n"
            "Total HT 120,00\nMontant TVA 24,00\nTotal TTC 144,00 MAD\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.lines[0].tax_rate, Decimal("20"))
        self.assertEqual(result.lines[0].tax_amount, Decimal("24.00"))
        self.assertEqual(result.lines[0].total_ttc, Decimal("144.00"))


class ItemLineParsingTests(SimpleTestCase):
    def test_common_item_line_layouts(self):
        cases = {
            "TRIO bougies piliers ivoire U 30 90.00 2 700.00": ("TRIO bougies piliers ivoire", "30", "U", "90.00", "2700.00"),
            "Eventail 500 25,00 12 500,00": ("Eventail", "500", "", "25.00", "12500.00"),
            "Verre à Vin 12P 55,00 dh 660,00 dh": ("Verre à Vin", "12", "", "55.00", "660.00"),
            "1GGS05 GIN GORDON'S 75 CL 100,00 235,00 235,00 23 500,00": ("GIN GORDON'S 75 CL", "100.00", "", "235.00", "23500.00"),
        }
        for source, (description, quantity, unit, unit_price, total) in cases.items():
            with self.subTest(source=source):
                line = parse_item_line(source)
                self.assertIsNotNone(line)
                self.assertEqual(line.description, description)
                self.assertEqual(line.quantity, Decimal(quantity))
                self.assertEqual(line.unit, unit)
                self.assertEqual(line.unit_price_ht, Decimal(unit_price))
                self.assertEqual(line.total_ht, Decimal(total))

    def test_reference_is_separated_from_the_description(self):
        line = parse_item_line("1GGS05 GIN GORDON'S 75 CL 100,00 235,00 235,00 23 500,00")

        self.assertEqual(line.reference, "1GGS05")

    def test_totals_and_footer_lines_are_not_items(self):
        for source in ("Total HT 120,00 240,00", "TEL 0524 42 32 82 2 1 2", "1 EURO 10,7211 10,7211"):
            with self.subTest(source=source):
                self.assertIsNone(parse_item_line(source))


class InvoiceNatureTests(SimpleTestCase):
    def test_goods_invoice(self):
        text = (
            "FACTURE N° 1171/2025 DATE : 22/10/2025\n"
            "CALICE FLUTE 13 oz 114 48,60 5 540,40\n"
            "Bouffat 70 cm U 30 140.00 4200,00\n"
            "BON DE LIVRAISON N° 2025\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.nature, NATURE_GOODS)

    def test_service_invoice(self):
        text = (
            "Facture N° 26-0067\n"
            "PRESTATION TECHNIQUE 66 540,00\nLUMIERE\nSONORISATION\nEQUIPE TECHNIQUE\n"
            "Montage et démontage, transport et déplacement\n"
            "TOTAL HT 66 540,00 MAD\nTVA20% 13 308,00 MAD\nTOTAL TTC 79 848,00 MAD\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.nature, NATURE_SERVICE)

    def test_rental_invoice(self):
        text = (
            "FACTURE 254\n"
            "LOCATION CAMION AVEC GRUE 200.00 10 2000,00\n"
            "LOCATION MANITOU 2.00 1500,00 3000,00\n"
            "Location chapiteau 1 4000,00 4000,00\n"
        )

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.nature, NATURE_RENTAL)

    def test_hotel_invoice_is_an_expense(self):
        text = "Arrival : 07/04/23 Departure : 09/04/23 Room N 512 Folio\nAccommodation 3,168.71\nHôtel"

        result = PurchaseInvoiceExtractor().extract(text)

        self.assertEqual(result.nature, NATURE_EXPENSE)

    def test_sales_invoice_issued_by_the_company_is_detected(self):
        extractor = PurchaseInvoiceExtractor(
            excluded_ices=["001443716000088"],
            excluded_names=["DELIGHT EVENT MANAGEMENT"],
        )
        text = (
            "MANDARIN ORIENTAL MARRAKECH ICE 001333760000021\n"
            "Facture N° : 26-2023 Date : 25/03/2023\n"
            "Perche Buffet 6 U 3000 18 000\n"
            "Compte : DELIGHT EVENT MANAGEMENT.\n"
        )

        self.assertEqual(extractor.extract(text).nature, NATURE_SALE)
        self.assertEqual(
            extractor.extract("Facture 5", title="5-3-2023 VENTES").nature,
            NATURE_SALE,
        )
