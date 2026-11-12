import json
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.error import URLError

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from openpyxl import load_workbook

from companies.models import Company
from documents.paperless_api import PaperlessDocument
from purchases.ai_extraction import (
    AiExtractionError,
    INVOICE_SCHEMA,
    OllamaInvoiceExtractor,
)
from purchases.models import InvoiceNature, PurchaseInvoice, Supplier


def invoice_payload(**changes):
    payload = {
        "document_type": "facture",
        "is_sale_invoice": False,
        "nature": "MARCHANDISES",
        "supplier": {"name": "SMARTECOM INNOVATION", "ice": "002 964 777 000 077"},
        "buyer": {
            "name": "DELIGHT EVENT MANAGEMENT",
            "tax_id": "001443716000088",
            "billing_address": "208 rue Ibn Toufail, Marrakech",
            "delivery_address": "Entrepôt Delight, Marrakech",
        },
        "invoice_number": "FA-2026-15",
        "purchase_order_number": "BC-1042",
        "invoice_date": "2026-05-14",
        "due_date": None,
        "currency": "MAD",
        "totals": {
            "subtotal_ht": 2600,
            "discount_amount": 100,
            "shipping_amount": 0,
            "net_ht": 2500,
            "tax_amount": 500,
            "total_ttc": 3000,
            "amount_due": 3000,
        },
        "payment": {
            "method": "Virement",
            "terms": "30 jours",
            "iban_or_rib": "MA64011519000001205000534921",
            "swift_or_bic": "BCPOMAMC",
        },
        "tax_breakdown": [{"rate": 20, "base": 2500, "amount": 500}],
        "lines": [
            {"reference": "G271", "description": "Ecran Xiaomi 27P G271", "quantity": 1,
             "unit": "U", "unit_price_ht": 1500, "tax_rate": 20, "total_ht": 1500},
            {"reference": None, "description": "Redmi A3x 64Go", "quantity": 2,
             "unit": None, "unit_price_ht": 500, "tax_rate": None, "total_ht": 1000},
        ],
        "warnings": [],
    }
    payload.update(changes)
    return payload


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def fake_http(payload, *, input_tokens=4000, output_tokens=600):
    response = {
        "message": {"role": "assistant", "content": json.dumps(payload)},
        "prompt_eval_count": input_tokens,
        "eval_count": output_tokens,
    }
    return Mock(return_value=FakeHttpResponse(response))


def extractor(http_open, model="qwen2.5vl:3b"):
    engine = OllamaInvoiceExtractor(
        model=model,
        http_open=http_open,
        excluded_ices=["001443716000088"],
        excluded_names=["DELIGHT EVENT MANAGEMENT"],
    )
    engine._render_pdf_pages = Mock(return_value=[b"page-1", b"page-2"])
    return engine


class OllamaExtractorTests(SimpleTestCase):
    def test_structured_invoice_is_converted_and_checked(self):
        http_open = fake_http(invoice_payload())

        result = extractor(http_open).extract_document(pdf_bytes=b"%PDF-1.4", title="16-5-2026 CF", page_count=2)
        invoice = result.extracted

        self.assertTrue(result.used_pdf)
        self.assertEqual(invoice.supplier_ice, "002964777000077")
        self.assertEqual(invoice.invoice_date, date(2026, 5, 14))
        self.assertEqual(len(invoice.lines), 2)
        self.assertEqual(invoice.lines[1].tax_rate, Decimal("20"))  # taux de la facture reporté
        self.assertEqual(invoice.lines[1].total_ttc, Decimal("1200.00"))
        self.assertEqual(invoice.nature, "MARCHANDISES")
        self.assertEqual(invoice.purchase_order_number, "BC-1042")
        self.assertEqual(invoice.buyer_name, "DELIGHT EVENT MANAGEMENT")
        self.assertEqual(invoice.delivery_address, "Entrepôt Delight, Marrakech")
        self.assertEqual(invoice.discount_amount, Decimal("100.00"))
        self.assertEqual(invoice.amount_due, Decimal("3000.00"))
        self.assertEqual(invoice.payment_method, "Virement")
        self.assertEqual(invoice.supplier_iban, "MA64011519000001205000534921")
        self.assertIn("Somme des lignes = total HT", invoice.notes)
        self.assertGreaterEqual(invoice.confidence, Decimal("90"))
        self.assertEqual(result.cost_usd, Decimal("0"))

        request = http_open.call_args.args[0]
        request_payload = json.loads(request.data)
        self.assertEqual(request_payload["model"], "qwen2.5vl:3b")
        self.assertEqual(request_payload["format"], INVOICE_SCHEMA)
        self.assertEqual(len(request_payload["messages"][1]["images"]), 2)
        self.assertIn("001443716000088", request_payload["messages"][0]["content"])

    def test_buyer_ice_returned_by_the_model_is_rejected(self):
        payload = invoice_payload(supplier={"name": "DELIGHT EVENT MANAGEMENT", "ice": "001443716000088"})

        invoice = extractor(fake_http(payload)).extract_document(text="texte").extracted

        self.assertEqual(invoice.supplier_ice, "")
        self.assertEqual(invoice.supplier_name, "")
        self.assertIn("société acheteuse", invoice.notes)

    def test_sale_invoices_and_inconsistent_lines_are_flagged(self):
        payload = invoice_payload(is_sale_invoice=True, totals={"net_ht": 9999, "tax_amount": 500, "total_ttc": 3000})

        invoice = extractor(fake_http(payload)).extract_document(text="texte").extracted

        self.assertEqual(invoice.nature, "VENTE")
        self.assertIn("diffère du total HT", invoice.notes)
        self.assertIn("Totaux incohérents", invoice.notes)

    def test_long_documents_are_sent_as_ocr_text(self):
        http_open = fake_http(invoice_payload())

        result = extractor(http_open).extract_document(pdf_bytes=b"%PDF", text="FACTURE 12", page_count=80)

        self.assertFalse(result.used_pdf)
        request_payload = json.loads(http_open.call_args.args[0].data)
        self.assertEqual(request_payload["messages"][1]["images"], [])
        self.assertIn("FACTURE 12", request_payload["messages"][1]["content"])

    def test_missing_structured_answer_raises_a_clear_error(self):
        http_open = Mock(return_value=FakeHttpResponse({"message": {"content": "?"}}))

        with self.assertRaises(AiExtractionError):
            extractor(http_open).extract_document(text="texte")

    def test_api_failure_raises_a_clear_error(self):
        http_open = Mock(side_effect=URLError("réseau indisponible"))

        with self.assertRaisesMessage(AiExtractionError, "réseau indisponible"):
            extractor(http_open).extract_document(text="texte")

    def test_no_key_is_required_for_the_local_engine(self):
        engine = OllamaInvoiceExtractor(api_url="http://ollama:11434")
        self.assertEqual(engine.api_url, "http://ollama:11434")


class CompareCommandTests(TestCase):
    def test_comparison_workbook_without_touching_purchases(self):
        company = Company.objects.create(code="DELIGHT", name="DELIGHT EVENT MANAGEMENT", ice="001443716000088")
        supplier = Supplier.objects.create(company=company, name="SMARTECOM", ice="002964777000077")
        PurchaseInvoice.objects.create(
            company=company, supplier=supplier, paperless_document_id=2642, nature=InvoiceNature.GOODS
        )
        before = list(PurchaseInvoice.objects.values_list("id", "updated_at"))
        paperless = Mock()
        paperless.get_document.side_effect = lambda document_id: PaperlessDocument(
            id=document_id, title="15-5-2026 CF", original_filename="x.pdf", created="2026-05-15",
            page_count=1, web_url="", content="XIAOMI AUTHORISED MI STORE\nTotal 3000,00",
        )
        paperless.download_pdf.return_value = b"%PDF-1.4"

        def build_extractor(**kwargs):
            engine = OllamaInvoiceExtractor(http_open=fake_http(invoice_payload()), **kwargs)
            engine._render_pdf_pages = Mock(return_value=[b"page"])
            return engine

        with TemporaryDirectory() as folder:
            output = Path(folder) / "comparaison.xlsx"
            with patch(
                "purchases.management.commands.compare_ai_extraction.PaperlessApiClient",
                return_value=paperless,
            ), patch(
                "purchases.management.commands.compare_ai_extraction.OllamaInvoiceExtractor",
                side_effect=build_extractor,
            ):
                call_command(
                    "compare_ai_extraction", "--company", "DELIGHT", "--sample", "3",
                    "--ids", "2895", "--models", "qwen2.5vl:3b", "--output", str(output),
                    stdout=StringIO(),
                )
            workbook = load_workbook(output)

        summary = list(workbook["Synthèse"].iter_rows(values_only=True))
        engines = [row[0] for row in summary[1:]]
        self.assertEqual(engines, ["règles actuelles", "qwen2.5vl:3b"])
        self.assertEqual(summary[2][2], "100 %")  # lignes = total HT avec l'IA
        self.assertEqual(summary[2][1], 2)  # #2895 (imposé) + #2642 (fournisseur principal)
        lines = list(workbook["Lignes lues par l’IA"].iter_rows(values_only=True))
        self.assertIn("Ecran Xiaomi 27P G271", [row[4] for row in lines])
        self.assertEqual(list(PurchaseInvoice.objects.values_list("id", "updated_at")), before)
