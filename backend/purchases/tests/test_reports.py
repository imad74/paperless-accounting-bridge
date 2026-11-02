from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from purchases.models import InvoiceNature, PurchaseInvoice, PurchaseInvoiceLine, Supplier
from purchases.reports import PurchaseReportFilterForm, build_report


def add_line(invoice, position, description, quantity, unit_price):
    total = Decimal(quantity) * Decimal(unit_price)
    return PurchaseInvoiceLine.objects.create(
        invoice=invoice,
        position=position,
        description=description,
        quantity=Decimal(quantity),
        unit_price_ht=Decimal(unit_price),
        tax_rate=Decimal("20"),
        total_ht=total,
        tax_amount=total * Decimal("0.2"),
        total_ttc=total * Decimal("1.2"),
    )


class PurchaseReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="R-A", name="Rapports A")
        other = Company.objects.create(code="R-B", name="Rapports B")
        cls.flowers = Supplier.objects.create(company=cls.company, name="Fleurs Atlas", activity="Fleuriste")
        cls.wood = Supplier.objects.create(company=cls.company, name="Menara Bois", activity="Bois")

        def invoice(supplier, number, day, net, status=PurchaseInvoice.Status.TO_REVIEW, company=None):
            return PurchaseInvoice.objects.create(
                company=company or cls.company,
                supplier=supplier,
                invoice_number=number,
                invoice_date=day,
                net_ht=Decimal(net),
                tax_amount=Decimal(net) * Decimal("0.2"),
                total_ttc=Decimal(net) * Decimal("1.2"),
                nature=InvoiceNature.GOODS,
                status=status,
            )

        jan = invoice(cls.flowers, "F-1", date(2026, 1, 10), "300")
        add_line(jan, 1, "ROSE ROUGE", "100", "2")
        add_line(jan, 2, "Rose blanche", "50", "2")
        feb = invoice(cls.flowers, "F-2", date(2026, 2, 5), "160", status=PurchaseInvoice.Status.VALIDATED)
        add_line(feb, 1, "rose rouge", "40", "4")
        wood = invoice(cls.wood, "B-1", date(2026, 2, 20), "1000")
        add_line(wood, 1, "MDF BRUT 18 mm", "10", "100")
        rejected = invoice(cls.wood, "B-X", date(2026, 2, 21), "999", status=PurchaseInvoice.Status.REJECTED)
        add_line(rejected, 1, "MDF BRUT 18 mm", "1", "999")
        foreign = invoice(None, "SECRET", date(2026, 2, 1), "5000", company=other)
        add_line(foreign, 1, "ROSE ROUGE", "1", "5000")

        cls.user = get_user_model().objects.create_user(username="report-viewer", password="x")
        CompanyMembership.objects.create(
            user=cls.user, company=cls.company, role=CompanyMembership.Role.VIEWER
        )

    def report(self, kind, **data):
        form = PurchaseReportFilterForm(data or None, company=self.company)
        if data:
            self.assertTrue(form.is_valid(), form.errors)
        return build_report(kind, self.company, form)

    def test_article_synthesis_groups_designations_and_excludes_rejected_and_other_companies(self):
        result = self.report("articles")
        by_article = {row["article"]: row for row in result.rows}

        self.assertEqual(set(by_article), {"rose rouge", "rose blanche", "mdf brut 18 mm"})
        rose = by_article["rose rouge"]
        self.assertEqual(rose["quantity"], Decimal("140"))
        self.assertEqual(rose["total_ht"], Decimal("360.00"))
        self.assertEqual(rose["average_price"], Decimal("2.5714"))
        self.assertEqual(rose["min_price"], Decimal("2"))
        self.assertEqual(rose["max_price"], Decimal("4"))
        self.assertEqual(by_article["mdf brut 18 mm"]["quantity"], Decimal("10"))

    def test_line_detail_filtered_by_period_supplier_and_designation(self):
        result = self.report(
            "lignes",
            date_from="2026-02-01",
            date_to="2026-02-28",
            supplier=str(self.flowers.pk),
            designation="rose",
            currency="MAD",
        )

        rows = list(result.rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["invoice__invoice_number"], "F-2")
        self.assertEqual(result.totals["total_ht"], Decimal("160.00"))

    def test_supplier_synthesis_uses_invoice_totals_without_double_counting(self):
        result = self.report("fournisseurs")
        by_supplier = {row["supplier_label"]: row for row in result.rows}

        self.assertEqual(by_supplier["Fleurs Atlas"]["net_ht"], Decimal("460.00"))
        self.assertEqual(by_supplier["Fleurs Atlas"]["invoices"], 2)
        self.assertEqual(by_supplier["Fleurs Atlas"]["lines"], 3)
        self.assertEqual(by_supplier["Menara Bois"]["net_ht"], Decimal("1000.00"))

    def test_supplier_synthesis_switches_to_lines_when_filtering_on_designation(self):
        result = self.report("fournisseurs", designation="rose rouge", currency="MAD")

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["net_ht"], Decimal("360.00"))
        self.assertIn("lignes", result.note)

    def test_monthly_synthesis_and_status_filter(self):
        result = self.report("mois")
        self.assertEqual(
            [(row["month"].month, row["net_ht"]) for row in result.rows],
            [(1, Decimal("300.00")), (2, Decimal("1160.00"))],
        )
        validated = self.report("mois", status=PurchaseInvoice.Status.VALIDATED, currency="MAD")
        self.assertEqual([row["net_ht"] for row in validated.rows], [Decimal("160.00")])

    def test_activity_filter(self):
        result = self.report("articles", activity="Bois", currency="MAD")

        self.assertEqual([row["article"] for row in result.rows], ["mdf brut 18 mm"])

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

    def test_report_pages_render_for_every_kind(self):
        self.login()
        for kind in ("lignes", "articles", "fournisseurs", "mois"):
            with self.subTest(kind=kind):
                response = self.client.get(reverse("purchases:report", args=(kind,)))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "SECRET")
        response = self.client.get(reverse("purchases:report", args=("articles",)))
        self.assertContains(response, "MDF BRUT 18 mm")

    def test_unknown_report_returns_404(self):
        self.login()

        response = self.client.get(reverse("purchases:report", args=("inconnu",)))

        self.assertEqual(response.status_code, 404)

    def test_excel_export_has_filters_header_rows_and_total(self):
        self.login()

        response = self.client.get(
            reverse("purchases:report", args=("lignes",)),
            {"designation": "rose", "currency": "MAD", "export": "xlsx"},
        )

        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        sheet = load_workbook(BytesIO(response.content)).active
        values = [row for row in sheet.iter_rows(values_only=True)]
        self.assertIn("Désignation : rose", values[1][0])
        descriptions = [row[6] for row in values if row and row[0] not in (None, "TOTAL")][3:]
        self.assertEqual(sorted(descriptions), ["ROSE ROUGE", "Rose blanche", "rose rouge"])
        self.assertEqual(values[-1][0], "TOTAL")
        self.assertEqual(values[-1][11], 460.0)

    def test_invalid_period_is_reported(self):
        self.login()

        response = self.client.get(
            reverse("purchases:report", args=("mois",)),
            {"date_from": "2026-03-01", "date_to": "2026-01-01"},
        )

        self.assertContains(response, "La date de début doit précéder la date de fin.")
