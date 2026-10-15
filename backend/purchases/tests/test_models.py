from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from companies.models import Company
from purchases.models import PurchaseInvoice, PurchaseInvoiceLine, Supplier


class PurchaseInvoiceModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="BUY", name="Achats")
        cls.other_company = Company.objects.create(code="OTHER", name="Autre")
        cls.supplier = Supplier.objects.create(company=cls.company, name="Fournisseur Alpha")

    def test_supplier_name_is_normalized_and_unique_per_company(self):
        self.assertEqual(self.supplier.normalized_name, "fournisseur alpha")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Supplier.objects.create(company=self.company, name="  FOURNISSEUR   ALPHA ")

    def test_supplier_from_another_company_is_rejected(self):
        foreign_supplier = Supplier.objects.create(company=self.other_company, name="Externe")
        invoice = PurchaseInvoice(company=self.company, supplier=foreign_supplier)

        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_invoice_balances_against_its_lines(self):
        invoice = PurchaseInvoice.objects.create(
            company=self.company,
            supplier=self.supplier,
            invoice_number="FA-1",
            invoice_date=date(2026, 10, 15),
            net_ht=Decimal("100.00"),
            tax_amount=Decimal("20.00"),
            total_ttc=Decimal("120.00"),
        )
        PurchaseInvoiceLine.objects.create(
            invoice=invoice,
            position=1,
            description="Prestation",
            quantity=Decimal("1"),
            unit_price_ht=Decimal("100"),
            tax_rate=Decimal("20"),
            total_ht=Decimal("100"),
            tax_amount=Decimal("20"),
            total_ttc=Decimal("120"),
            verified=True,
        )

        self.assertTrue(invoice.is_balanced)
        self.assertEqual(invoice.line_net_ht_total, Decimal("100"))

    def test_paperless_document_is_unique_within_company(self):
        PurchaseInvoice.objects.create(company=self.company, paperless_document_id=42)

        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseInvoice.objects.create(company=self.company, paperless_document_id=42)

        PurchaseInvoice.objects.create(company=self.other_company, paperless_document_id=42)

