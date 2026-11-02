from io import BytesIO, StringIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from purchases.directory import PLACEHOLDER_PREFIX, SupplierDirectoryBuilder
from purchases.models import InvoiceNature, Supplier
from purchases.services import PurchaseInvoiceImportService, extractor_for_company
from purchases.tests.test_bulk_import import GOODS_TEXT, SERVICE_TEXT, paperless_document


UNREADABLE_TEXT = """Facture 77
le 02/04/2026
VERRERIE ATLAS SARL ICE : 000216716000096
"""


class SupplierDirectoryBuilderTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="DELIGHT", name="DELIGHT EVENT MANAGEMENT", ice="001443716000088"
        )

    def builder(self):
        return SupplierDirectoryBuilder(
            company=self.company, extractor=extractor_for_company(self.company)
        )

    def test_suppliers_are_grouped_by_ice_with_majority_nature(self):
        builder = self.builder()
        for index in range(3):
            builder.add_document(paperless_document(index, GOODS_TEXT, "89-10-2025"))
        # Même fournisseur, ICE mal lu d'un chiffre.
        builder.add_document(
            paperless_document(9, GOODS_TEXT.replace("000216716000096", "000216716000098"), "90-10-2025")
        )
        builder.add_document(paperless_document(20, SERVICE_TEXT))
        builder.save()

        goods_supplier = Supplier.objects.get(company=self.company, ice="000216716000096")
        self.assertEqual(goods_supplier.paperless_document_count, 4)
        self.assertEqual(goods_supplier.detected_nature, InvoiceNature.GOODS)
        self.assertEqual(goods_supplier.name, "VERRERIE ATLAS")
        self.assertEqual(str(goods_supplier.detected_total_ttc), "46753.92")
        self.assertEqual(goods_supplier.first_document_date.isoformat(), "2025-10-22")
        service_supplier = Supplier.objects.get(company=self.company, ice="002887911000047")
        self.assertEqual(service_supplier.detected_nature, InvoiceNature.SERVICE)
        self.assertEqual(Supplier.objects.filter(company=self.company).count(), 2)

    def test_validated_nature_activity_and_name_are_never_overwritten(self):
        supplier = Supplier.objects.create(
            company=self.company,
            name="Verrerie Atlas",
            ice="000216716000096",
            activity="Verrerie",
            default_nature=InvoiceNature.RENTAL,
        )
        builder = self.builder()
        builder.add_document(paperless_document(1, GOODS_TEXT, "89-10-2025"))
        builder.save()

        supplier.refresh_from_db()
        self.assertEqual(supplier.name, "Verrerie Atlas")
        self.assertEqual(supplier.activity, "Verrerie")
        self.assertEqual(supplier.default_nature, InvoiceNature.RENTAL)
        self.assertEqual(supplier.detected_nature, InvoiceNature.GOODS)
        self.assertEqual(supplier.effective_nature, InvoiceNature.RENTAL)

    def test_supplier_without_readable_name_gets_a_placeholder(self):
        builder = self.builder()
        builder.add_document(paperless_document(1, "Facture 5\nICE : 003389378000086\n"))
        builder.save()

        supplier = Supplier.objects.get(company=self.company, ice="003389378000086")
        self.assertTrue(supplier.name.startswith(PLACEHOLDER_PREFIX))

    def test_command_dry_run_saves_nothing(self):
        client = Mock()
        client.iter_documents.return_value = iter(
            [paperless_document(1, GOODS_TEXT, "89-10-2025"), paperless_document(2, SERVICE_TEXT)]
        )
        output = StringIO()
        with patch(
            "purchases.management.commands.build_supplier_directory.PaperlessApiClient",
            return_value=client,
        ):
            call_command("build_supplier_directory", "--company", "DELIGHT", "--dry-run", stdout=output)

        self.assertIn("Fournisseurs distincts : 2", output.getvalue())
        self.assertFalse(Supplier.objects.exists())

    def test_unreadable_invoice_takes_the_nature_known_for_its_supplier(self):
        Supplier.objects.create(
            company=self.company,
            name="VERRERIE ATLAS",
            ice="000216716000096",
            detected_nature=InvoiceNature.GOODS,
            paperless_document_count=12,
        )
        service = PurchaseInvoiceImportService(client=Mock())

        invoice, created = service.import_document(
            company=self.company,
            paperless_document=paperless_document(5, UNREADABLE_TEXT, "80-4-2026"),
            allowed_natures={InvoiceNature.GOODS},
        )

        self.assertTrue(created)
        self.assertEqual(invoice.nature, InvoiceNature.GOODS)
        self.assertIn("annuaire fournisseurs", invoice.extraction_notes)


class SupplierViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="S-A", name="Fournisseurs A")
        cls.other_company = Company.objects.create(code="S-B", name="Fournisseurs B")
        cls.users = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(username=f"supplier-{role.lower()}", password="x")
            CompanyMembership.objects.create(user=user, company=cls.company, role=role)
            cls.users[role] = user
        cls.goods = Supplier.objects.create(
            company=cls.company, name="Fleurs Atlas", ice="000000000000001",
            detected_nature=InvoiceNature.GOODS, paperless_document_count=30,
        )
        cls.service = Supplier.objects.create(
            company=cls.company, name="Transports Sud", ice="000000000000002",
            detected_nature=InvoiceNature.GOODS, default_nature=InvoiceNature.SERVICE,
            paperless_document_count=5,
        )
        cls.foreign = Supplier.objects.create(company=cls.other_company, name="SECRET B")

    def login(self, role):
        self.client.force_login(self.users[role])
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

    def test_list_is_company_scoped_and_filters_on_the_retained_nature(self):
        self.login(CompanyMembership.Role.VIEWER)

        response = self.client.get(reverse("purchases:supplier_list"), {"nature": InvoiceNature.GOODS})

        self.assertContains(response, "Fleurs Atlas")
        self.assertNotContains(response, "Transports Sud")
        self.assertNotContains(response, "SECRET B")

    def test_operator_sets_activity_and_validated_nature(self):
        self.login(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("purchases:supplier_update", args=(self.goods.pk,)),
            {
                "name": "Fleurs Atlas",
                "ice": "000000000000001",
                "if_number": "",
                "rc": "",
                "activity": "  fleuriste ",
                "default_nature": InvoiceNature.GOODS,
                "address": "",
                "city": "",
                "country": "Maroc",
                "active": "on",
            },
        )

        self.assertRedirects(response, reverse("purchases:supplier_list"))
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.activity, "Fleuriste")
        self.assertEqual(self.goods.default_nature, InvoiceNature.GOODS)

    def test_viewer_cannot_edit_a_supplier(self):
        self.login(CompanyMembership.Role.VIEWER)

        response = self.client.get(reverse("purchases:supplier_update", args=(self.goods.pk,)))

        self.assertIn(response.status_code, (302, 403))

    def test_supplier_of_another_company_is_not_editable(self):
        self.login(CompanyMembership.Role.ADMIN)

        response = self.client.get(reverse("purchases:supplier_update", args=(self.foreign.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_excel_export_contains_the_filtered_suppliers(self):
        self.login(CompanyMembership.Role.VIEWER)

        response = self.client.get(reverse("purchases:supplier_export"), {"nature": InvoiceNature.SERVICE})

        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        sheet = load_workbook(BytesIO(response.content)).active
        names = [row[0] for row in sheet.iter_rows(min_row=2, values_only=True)]
        self.assertEqual(names, ["Transports Sud"])
        self.assertEqual(sheet["F2"].value, "Prestation de service")


class AutomaticNatureValidationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="DELIGHT", name="DELIGHT EVENT MANAGEMENT", ice="001443716000088"
        )

    def build(self, documents, **options):
        builder = SupplierDirectoryBuilder(
            company=self.company, extractor=extractor_for_company(self.company)
        )
        for document in documents:
            builder.add_document(document)
        builder.save(**options)

    def test_detected_nature_is_validated_automatically_and_recalculated(self):
        self.build([paperless_document(1, GOODS_TEXT, "89-10-2025")], auto_validate=True)
        supplier = Supplier.objects.get(ice="000216716000096")
        self.assertEqual(supplier.default_nature, InvoiceNature.GOODS)
        self.assertEqual(supplier.nature_validation, Supplier.NatureValidation.AUTO)

        # Nouvelle analyse : le fournisseur s'avère surtout prestataire de service.
        documents = [paperless_document(1, GOODS_TEXT, "89-10-2025")] + [
            paperless_document(
                10 + i,
                SERVICE_TEXT.replace("002887911000047", "000216716000096"),
            )
            for i in range(4)
        ]
        self.build(documents)
        supplier.refresh_from_db()
        self.assertEqual(supplier.detected_nature, InvoiceNature.SERVICE)
        self.assertEqual(supplier.default_nature, InvoiceNature.SERVICE)
        self.assertEqual(supplier.nature_validation, Supplier.NatureValidation.AUTO)

    def test_manual_validation_is_never_changed(self):
        Supplier.objects.create(
            company=self.company,
            name="Verrerie Atlas",
            ice="000216716000096",
            default_nature=InvoiceNature.RENTAL,
            nature_validation=Supplier.NatureValidation.MANUAL,
        )
        self.build([paperless_document(1, GOODS_TEXT, "89-10-2025")], auto_validate=True)

        supplier = Supplier.objects.get(ice="000216716000096")
        self.assertEqual(supplier.default_nature, InvoiceNature.RENTAL)
        self.assertEqual(supplier.nature_validation, Supplier.NatureValidation.MANUAL)

    def test_command_validates_existing_directory_without_rescanning(self):
        Supplier.objects.create(
            company=self.company, name="A", ice="000000000000001",
            detected_nature=InvoiceNature.GOODS, paperless_document_count=3,
        )
        Supplier.objects.create(
            company=self.company, name="B", ice="000000000000002",
            detected_nature=InvoiceNature.UNKNOWN, paperless_document_count=8,
        )
        Supplier.objects.create(
            company=self.company, name="C", ice="000000000000003",
            detected_nature=InvoiceNature.GOODS, default_nature=InvoiceNature.SERVICE,
            nature_validation=Supplier.NatureValidation.MANUAL, paperless_document_count=5,
        )
        output = StringIO()

        call_command("auto_validate_suppliers", "--company", "DELIGHT", stdout=output)

        values = dict(Supplier.objects.values_list("name", "default_nature"))
        self.assertEqual(values, {"A": "MARCHANDISES", "B": "", "C": "SERVICE"})
        self.assertIn("validées automatiquement : 1", output.getvalue())


class SupplierFormValidationTests(SupplierViewTests):
    def post_supplier(self, supplier, **changes):
        data = {
            "name": supplier.name,
            "ice": supplier.ice,
            "if_number": "",
            "rc": "",
            "activity": "",
            "default_nature": supplier.default_nature,
            "address": "",
            "city": "",
            "country": "Maroc",
            "active": "on",
        }
        data.update(changes)
        return self.client.post(reverse("purchases:supplier_update", args=(supplier.pk,)), data)

    def test_changing_the_nature_by_hand_makes_it_manual(self):
        self.goods.default_nature = InvoiceNature.GOODS
        self.goods.nature_validation = Supplier.NatureValidation.AUTO
        self.goods.save()
        self.login(CompanyMembership.Role.OPERATOR)

        self.post_supplier(self.goods, default_nature=InvoiceNature.SERVICE)

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.default_nature, InvoiceNature.SERVICE)
        self.assertEqual(self.goods.nature_validation, Supplier.NatureValidation.MANUAL)

    def test_confirming_an_automatic_nature_makes_it_manual(self):
        self.goods.default_nature = InvoiceNature.GOODS
        self.goods.nature_validation = Supplier.NatureValidation.AUTO
        self.goods.save()
        self.login(CompanyMembership.Role.OPERATOR)

        self.post_supplier(self.goods, confirm_nature="on")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.nature_validation, Supplier.NatureValidation.MANUAL)

    def test_saving_without_touching_the_nature_keeps_it_automatic(self):
        self.goods.default_nature = InvoiceNature.GOODS
        self.goods.nature_validation = Supplier.NatureValidation.AUTO
        self.goods.save()
        self.login(CompanyMembership.Role.OPERATOR)

        self.post_supplier(self.goods, activity="Fleuriste")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.activity, "Fleuriste")
        self.assertEqual(self.goods.nature_validation, Supplier.NatureValidation.AUTO)
