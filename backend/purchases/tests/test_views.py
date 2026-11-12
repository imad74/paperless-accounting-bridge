from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from purchases.models import (
    PurchaseInvoice,
    PurchaseInvoiceAnalysisJob,
    PurchaseInvoiceLine,
    Supplier,
)


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
                "supplier_ice_raw": "",
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

    def test_invoice_with_many_lines_can_be_saved(self):
        """Plus de 1 000 champs envoyés : ne doit pas provoquer d'erreur 400."""
        self.login(CompanyMembership.Role.OPERATOR)
        line_count = 90
        data = {
            "supplier": self.supplier.pk,
            "supplier_name_raw": "",
            "supplier_ice_raw": "",
            "nature": "MARCHANDISES",
            "invoice_number": "A-100",
            "invoice_date": "2026-10-15",
            "due_date": "",
            "currency": "MAD",
            "subtotal_ht": "",
            "discount_amount": "0",
            "net_ht": str(line_count),
            "tax_amount": str(line_count * 0.2),
            "total_ttc": str(line_count * 1.2),
            "extraction_notes": "",
            "lines-TOTAL_FORMS": str(line_count),
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
        }
        for index in range(line_count):
            data.update({
                f"lines-{index}-position": str(index + 1),
                f"lines-{index}-reference": f"REF-{index}",
                f"lines-{index}-description": f"Article {index}",
                f"lines-{index}-quantity": "1",
                f"lines-{index}-unit": "U",
                f"lines-{index}-unit_price_ht": "1",
                f"lines-{index}-discount_percent": "0",
                f"lines-{index}-tax_rate": "20",
                f"lines-{index}-total_ht": "1",
                f"lines-{index}-tax_amount": "0.20",
                f"lines-{index}-total_ttc": "1.20",
            })
        self.assertGreater(len(data), 1000)

        response = self.client.post(reverse("purchases:update", args=(self.invoice.pk,)), data)

        self.assertRedirects(response, reverse("purchases:update", args=(self.invoice.pk,)))
        self.assertEqual(self.invoice.lines.count(), line_count)


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

    def test_operator_can_refresh_supplier_name_and_ice_from_ocr(self):
        extracted_supplier = Supplier.objects.create(
            company=self.company,
            name="EVENT PRINT",
            ice="001234567890123",
        )
        invoice = PurchaseInvoice.objects.create(
            company=self.company,
            paperless_document_id=7890,
            raw_ocr_text=(
                "Fournisseur : EVENT PRINT\n"
                "ICE : 001234567890123\n"
                "Facture N° FA-1"
            ),
        )
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:refresh_supplier", args=(invoice.pk,))
        )

        self.assertRedirects(response, reverse("purchases:update", args=(invoice.pk,)))
        invoice.refresh_from_db()
        self.assertEqual(invoice.supplier_name_raw, "EVENT PRINT")
        self.assertEqual(invoice.supplier_ice_raw, "001234567890123")
        self.assertEqual(invoice.supplier, extracted_supplier)

    def test_viewer_cannot_refresh_supplier_identity(self):
        self.login(CompanyMembership.Role.VIEWER)

        response = self.client.post(
            reverse("purchases:refresh_supplier", args=(self.invoice.pk,))
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(PURCHASES_AI_ENABLED=True)
    def test_operator_can_start_ai_analysis(self):
        self.invoice.paperless_document_id = 7890
        self.invoice.save(update_fields=("paperless_document_id", "updated_at"))
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:analyze_ai", args=(self.invoice.pk,))
        )

        self.assertRedirects(response, reverse("purchases:update", args=(self.invoice.pk,)))
        job = PurchaseInvoiceAnalysisJob.objects.get(invoice=self.invoice)
        self.assertEqual(job.status, PurchaseInvoiceAnalysisJob.Status.PENDING)
        self.assertEqual(job.requested_by, self.users[CompanyMembership.Role.OPERATOR])
        self.assertEqual(job.model_name, "qwen2.5vl:3b")

    def test_ai_analysis_is_rejected_when_local_engine_is_disabled(self):
        self.invoice.paperless_document_id = 7890
        self.invoice.save(update_fields=("paperless_document_id", "updated_at"))
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:analyze_ai", args=(self.invoice.pk,)), follow=True
        )

        self.assertContains(response, "L’analyse IA locale n’est pas activée")
        self.assertFalse(PurchaseInvoiceAnalysisJob.objects.filter(invoice=self.invoice).exists())

    def test_viewer_cannot_start_ai_analysis(self):
        self.login(CompanyMembership.Role.VIEWER)

        response = self.client.post(
            reverse("purchases:analyze_ai", args=(self.invoice.pk,))
        )

        self.assertEqual(response.status_code, 403)
