from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from purchases.models import PurchaseInvoice, PurchaseInvoiceLine, Supplier


class PurchaseInvoiceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="P-A", name="Achats A")
        cls.other_company = Company.objects.create(code="P-B", name="Achats B")
        cls.users = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(
                username=f"purchase-{role.lower()}",
                password="test-password",
            )
            CompanyMembership.objects.create(user=user, company=cls.company, role=role)
            cls.users[role] = user
        cls.supplier = Supplier.objects.create(company=cls.company, name="Alpha")
        cls.invoice = PurchaseInvoice.objects.create(
            company=cls.company,
            supplier=cls.supplier,
            invoice_number="A-100",
            invoice_date=date(2026, 10, 15),
            net_ht=Decimal("100"),
            tax_amount=Decimal("20"),
            total_ttc=Decimal("120"),
        )
        cls.other_invoice = PurchaseInvoice.objects.create(
            company=cls.other_company,
            invoice_number="SECRET-B",
        )

    def login(self, role):
        self.client.force_login(self.users[role])
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

    def test_list_is_company_scoped_for_all_roles(self):
        for role in CompanyMembership.Role.values:
            with self.subTest(role=role):
                self.client.logout()
                self.login(role)
                response = self.client.get(reverse("purchases:list"))
                self.assertContains(response, "A-100")
                self.assertNotContains(response, "SECRET-B")

    def test_viewer_cannot_import_or_edit(self):
        self.login(CompanyMembership.Role.VIEWER)

        self.assertEqual(self.client.get(reverse("purchases:import")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("purchases:update", args=(self.invoice.pk,))).status_code,
            403,
        )

    @patch("purchases.views.PurchaseInvoiceImportService")
    def test_operator_can_import_and_is_redirected_to_review(self, service_class):
        self.login(CompanyMembership.Role.OPERATOR)
        service_class.return_value.import_document.return_value = (self.invoice, True)

        response = self.client.post(
            reverse("purchases:import"),
            {"paperless_document_id": 7890},
        )

        self.assertRedirects(response, reverse("purchases:update", args=(self.invoice.pk,)))

    def test_manager_can_validate_balanced_verified_invoice(self):
        PurchaseInvoiceLine.objects.create(
            invoice=self.invoice,
            position=1,
            description="Service",
            quantity=1,
            unit_price_ht=100,
            tax_rate=20,
            total_ht=100,
            tax_amount=20,
            total_ttc=120,
            verified=True,
        )
        self.login(CompanyMembership.Role.MANAGER)

        response = self.client.post(reverse("purchases:validate", args=(self.invoice.pk,)))

        self.assertRedirects(response, reverse("purchases:update", args=(self.invoice.pk,)))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, PurchaseInvoice.Status.VALIDATED)

    def test_manager_cannot_validate_an_unverified_line(self):
        PurchaseInvoiceLine.objects.create(
            invoice=self.invoice,
            position=1,
            description="Service à contrôler",
            quantity=1,
            unit_price_ht=100,
            tax_rate=20,
            total_ht=100,
            tax_amount=20,
            total_ttc=120,
            verified=False,
        )
        self.login(CompanyMembership.Role.MANAGER)

        response = self.client.post(
            reverse("purchases:validate", args=(self.invoice.pk,)),
            follow=True,
        )

        self.assertContains(response, "marquer toutes les lignes comme vérifiées")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, PurchaseInvoice.Status.TO_REVIEW)

    def test_manager_cannot_validate_another_company_invoice(self):
        self.login(CompanyMembership.Role.MANAGER)

        response = self.client.post(
            reverse("purchases:validate", args=(self.other_invoice.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_operator_cannot_validate(self):
        self.login(CompanyMembership.Role.OPERATOR)
        response = self.client.post(reverse("purchases:validate", args=(self.invoice.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_update_page_can_add_multiple_invoice_lines(self):
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:update", args=(self.invoice.pk,)),
            {
                "supplier": self.supplier.pk,
                "supplier_name_raw": "",
                "invoice_number": "A-100",
                "invoice_date": "2026-10-15",
                "due_date": "",
                "currency": "mad",
                "subtotal_ht": "",
                "discount_amount": "0",
                "net_ht": "150",
                "tax_amount": "30",
                "total_ttc": "180",
                "extraction_notes": "Contrôlée",
                "lines-TOTAL_FORMS": "2",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-position": "1",
                "lines-0-reference": "ART-1",
                "lines-0-description": "Article un",
                "lines-0-quantity": "2",
                "lines-0-unit": "U",
                "lines-0-unit_price_ht": "50",
                "lines-0-discount_percent": "0",
                "lines-0-tax_rate": "20",
                "lines-0-total_ht": "100",
                "lines-0-tax_amount": "20",
                "lines-0-total_ttc": "120",
                "lines-0-verified": "on",
                "lines-1-position": "2",
                "lines-1-reference": "SRV-1",
                "lines-1-description": "Service deux",
                "lines-1-quantity": "1",
                "lines-1-unit": "Forfait",
                "lines-1-unit_price_ht": "50",
                "lines-1-discount_percent": "0",
                "lines-1-tax_rate": "20",
                "lines-1-total_ht": "50",
                "lines-1-tax_amount": "10",
                "lines-1-total_ttc": "60",
                "lines-1-verified": "on",
            },
        )

        self.assertRedirects(response, reverse("purchases:update", args=(self.invoice.pk,)))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.currency, "MAD")
        self.assertEqual(self.invoice.lines.count(), 2)
        summary = self.invoice.tax_summaries.get()
        self.assertEqual(summary.tax_rate, Decimal("20"))
        self.assertEqual(summary.taxable_amount, Decimal("150"))
        self.assertEqual(summary.tax_amount, Decimal("30"))

    def test_update_page_contains_dynamic_line_controls(self):
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.get(reverse("purchases:update", args=(self.invoice.pk,)))

        self.assertContains(response, "data-add-invoice-line")
        self.assertContains(response, "invoice-line-empty-form")
        self.assertContains(response, "lines-__prefix__-description")

    def test_duplicate_supplier_name_is_reported_in_the_form(self):
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:supplier_create"),
            {
                "name": "  ALPHA  ",
                "ice": "",
                "if_number": "",
                "rc": "",
                "address": "",
                "city": "",
                "country": "Maroc",
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un fournisseur portant ce nom existe déjà")
        self.assertEqual(Supplier.objects.filter(company=self.company).count(), 1)
