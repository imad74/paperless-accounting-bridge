from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from documents.forms import DocumentForm
from documents.models import Document, DocumentType


class DocumentFormTests(TestCase):
    def test_only_business_fields_are_exposed(self):
        self.assertEqual(
            list(DocumentForm().fields),
            [
                "title",
                "document_type",
                "document_date",
                "amount",
                "currency",
                "notes",
            ],
        )

    def test_currency_is_normalized(self):
        document_type = DocumentType.objects.create(
            code="CUR",
            name="Devise",
            prefix="CUR",
        )
        form = DocumentForm(
            data={
                "title": "Document en euros",
                "document_type": document_type.pk,
                "document_date": "2026-08-04",
                "amount": "10.00",
                "currency": " eur ",
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["currency"], "EUR")


class DocumentViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="DOC-A", name="Documents A")
        cls.other_company = Company.objects.create(
            code="DOC-B",
            name="Documents B",
        )
        cls.users = {}
        cls.memberships = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(
                username=f"document-{role.lower()}",
                password="test-password",
            )
            membership = CompanyMembership.objects.create(
                user=user,
                company=cls.company,
                role=role,
            )
            cls.users[role] = user
            cls.memberships[role] = membership

        cls.user_without_membership = get_user_model().objects.create_user(
            username="document-no-membership",
            password="test-password",
        )
        cls.invoice_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        cls.credit_type = DocumentType.objects.create(
            code="CRN",
            name="Avoir",
            prefix="AV",
        )
        cls.create_type = DocumentType.objects.create(
            code="PUR",
            name="Achat",
            prefix="AC",
        )
        cls.inactive_type = DocumentType.objects.create(
            code="OLD",
            name="Ancien type",
            prefix="OLD",
            active=False,
        )
        cls.document = Document.objects.create(
            number="FN-DOC-A-000001-2026",
            title="Facture Alpha",
            company=cls.company,
            document_type=cls.invoice_type,
            original_filename="alpha.pdf",
            stored_filename="alpha-stored.pdf",
            document_date=date(2026, 8, 4),
            amount=Decimal("120.50"),
            currency="MAD",
            status=Document.Status.NEW,
        )
        cls.credit_document = Document.objects.create(
            number="AV-DOC-A-000001-2026",
            title="Avoir Beta",
            company=cls.company,
            document_type=cls.credit_type,
            original_filename="beta.pdf",
            stored_filename="beta-stored.pdf",
            document_date=date(2026, 7, 15),
            status=Document.Status.IMPORTED,
        )
        cls.other_document = Document.objects.create(
            number="FN-DOC-B-000001-2026",
            title="Document interdit",
            company=cls.other_company,
            document_type=cls.invoice_type,
            original_filename="forbidden.pdf",
            stored_filename="forbidden.pdf",
            document_date=date(2026, 8, 4),
        )

    def login_with_company(self, role):
        self.client.force_login(self.users[role])
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

    def document_data(self, **overrides):
        data = {
            "title": "Nouvel achat",
            "document_type": self.create_type.pk,
            "document_date": "2026-08-04",
            "amount": "45.75",
            "currency": "mad",
            "notes": "Créé depuis le formulaire",
        }
        data.update(overrides)
        return data

    def test_documents_are_mounted_in_the_main_routing(self):
        self.assertEqual(reverse("documents:list"), "/documents/")
        self.assertEqual(reverse("documents:create"), "/documents/new/")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("documents:list"))

        self.assertRedirects(
            response,
            f"/admin/login/?next={reverse('documents:list')}",
            fetch_redirect_response=False,
        )

    def test_user_without_membership_is_sent_to_company_selector(self):
        self.client.force_login(self.user_without_membership)

        response = self.client.get(reverse("documents:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fdocuments%2F",
            fetch_redirect_response=False,
        )

    def test_inactive_membership_cannot_list_documents(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        CompanyMembership.objects.filter(pk=membership.pk).update(active=False)
        self.login_with_company(CompanyMembership.Role.VIEWER)

        response = self.client.get(reverse("documents:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fdocuments%2F",
            fetch_redirect_response=False,
        )

    def test_all_roles_only_see_active_company_documents(self):
        for role in CompanyMembership.Role.values:
            with self.subTest(role=role):
                self.client.logout()
                self.login_with_company(role)

                response = self.client.get(reverse("documents:list"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.document.number)
                self.assertContains(response, self.credit_document.number)
                self.assertNotContains(response, self.other_document.number)

    def test_list_supports_search_type_status_and_period_filters(self):
        self.login_with_company(CompanyMembership.Role.VIEWER)

        search_response = self.client.get(
            reverse("documents:list"),
            {"q": "alpha"},
        )
        type_response = self.client.get(
            reverse("documents:list"),
            {"document_type": self.credit_type.pk},
        )
        status_response = self.client.get(
            reverse("documents:list"),
            {"status": Document.Status.IMPORTED},
        )
        period_response = self.client.get(
            reverse("documents:list"),
            {"period": "2026-08"},
        )

        self.assertContains(search_response, self.document.number)
        self.assertNotContains(search_response, self.credit_document.number)
        self.assertContains(type_response, self.credit_document.number)
        self.assertNotContains(type_response, self.document.number)
        self.assertContains(status_response, self.credit_document.number)
        self.assertNotContains(status_response, self.document.number)
        self.assertContains(period_response, self.document.number)
        self.assertNotContains(period_response, self.credit_document.number)

    def test_invalid_period_displays_an_error_without_failing(self):
        self.login_with_company(CompanyMembership.Role.VIEWER)

        response = self.client.get(
            reverse("documents:list"),
            {"period": "2026-99"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saisissez une période valide.")

    def test_pagination_preserves_all_filters(self):
        for index in range(21):
            Document.objects.create(
                number=f"FN-DOC-A-{index + 100:06d}-2026",
                title=f"Paginer {index:02d}",
                company=self.company,
                document_type=self.invoice_type,
                original_filename=f"page-{index}.pdf",
                stored_filename=f"page-{index}.pdf",
                document_date=date(2026, 8, 4),
                status=Document.Status.NEW,
            )
        self.login_with_company(CompanyMembership.Role.VIEWER)
        query = (
            f"q=Paginer&document_type={self.invoice_type.pk}"
            "&status=NEW&period=2026-08"
        )

        response = self.client.get(f"{reverse('documents:list')}?{query}")

        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(response.context["pagination_query"], query)
        self.assertContains(response, f"?page=2&amp;{query.replace('&', '&amp;')}")

    def test_admin_manager_and_operator_can_open_document_forms(self):
        for role in (
            CompanyMembership.Role.ADMIN,
            CompanyMembership.Role.MANAGER,
            CompanyMembership.Role.OPERATOR,
        ):
            with self.subTest(role=role):
                self.client.logout()
                self.login_with_company(role)

                create_response = self.client.get(reverse("documents:create"))
                update_response = self.client.get(
                    reverse("documents:update", args=[self.document.pk])
                )

                self.assertEqual(create_response.status_code, 200)
                self.assertEqual(update_response.status_code, 200)

    def test_viewer_cannot_create_update_or_archive_documents(self):
        self.login_with_company(CompanyMembership.Role.VIEWER)

        create_response = self.client.post(
            reverse("documents:create"),
            self.document_data(),
        )
        update_response = self.client.post(
            reverse("documents:update", args=[self.document.pk]),
            self.document_data(),
        )
        archive_response = self.client.post(
            reverse("documents:archive", args=[self.document.pk])
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(archive_response.status_code, 403)

    def test_creation_generates_server_controlled_fields(self):
        self.login_with_company(CompanyMembership.Role.OPERATOR)
        data = self.document_data(
            company=self.other_company.pk,
            number="FORGED-NUMBER",
            status=Document.Status.ARCHIVED,
            created_by=self.users[CompanyMembership.Role.ADMIN].pk,
            stored_filename="forged.pdf",
            sha256="0" * 64,
        )

        response = self.client.post(
            reverse("documents:create"),
            data,
            follow=True,
        )

        self.assertRedirects(response, reverse("documents:list"))
        document = Document.objects.get(title="Nouvel achat")
        self.assertEqual(document.company, self.company)
        self.assertEqual(
            document.created_by,
            self.users[CompanyMembership.Role.OPERATOR],
        )
        self.assertEqual(document.status, Document.Status.NEW)
        self.assertEqual(document.number, "AC-DOC-A-000001-2026")
        self.assertEqual(document.currency, "MAD")
        self.assertEqual(document.stored_filename, "")
        self.assertIsNone(document.sha256)
        self.assertContains(response, "Document créé avec succès.")

    def test_inactive_document_type_cannot_be_used_for_creation(self):
        self.login_with_company(CompanyMembership.Role.OPERATOR)

        response = self.client.post(
            reverse("documents:create"),
            self.document_data(document_type=self.inactive_type.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "document_type",
            "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        )
        self.assertFalse(Document.objects.filter(title="Nouvel achat").exists())

    def test_update_preserves_server_controlled_fields(self):
        self.login_with_company(CompanyMembership.Role.OPERATOR)
        original_number = self.document.number
        response = self.client.post(
            reverse("documents:update", args=[self.document.pk]),
            self.document_data(
                title="Facture Alpha modifiée",
                document_type=self.invoice_type.pk,
                company=self.other_company.pk,
                number="FORGED-NUMBER",
                status=Document.Status.ARCHIVED,
            ),
            follow=True,
        )

        self.assertRedirects(response, reverse("documents:list"))
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Facture Alpha modifiée")
        self.assertEqual(self.document.company, self.company)
        self.assertEqual(self.document.number, original_number)
        self.assertEqual(self.document.status, Document.Status.NEW)
        self.assertContains(response, "Document modifié avec succès.")

    def test_update_and_archive_cannot_target_another_company(self):
        self.login_with_company(CompanyMembership.Role.ADMIN)

        update_response = self.client.post(
            reverse("documents:update", args=[self.other_document.pk]),
            self.document_data(),
        )
        archive_response = self.client.post(
            reverse("documents:archive", args=[self.other_document.pk])
        )

        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(archive_response.status_code, 404)
        self.other_document.refresh_from_db()
        self.assertNotEqual(self.other_document.status, Document.Status.ARCHIVED)

    def test_admin_and_manager_can_archive_a_document(self):
        for role in (
            CompanyMembership.Role.ADMIN,
            CompanyMembership.Role.MANAGER,
        ):
            with self.subTest(role=role):
                Document.objects.filter(pk=self.document.pk).update(
                    status=Document.Status.NEW
                )
                self.client.logout()
                self.login_with_company(role)

                response = self.client.post(
                    reverse("documents:archive", args=[self.document.pk]),
                    follow=True,
                )

                self.document.refresh_from_db()
                self.assertEqual(self.document.status, Document.Status.ARCHIVED)
                self.assertContains(response, "Document archivé avec succès.")

    def test_operator_cannot_archive_and_get_is_not_allowed(self):
        self.login_with_company(CompanyMembership.Role.OPERATOR)
        operator_response = self.client.post(
            reverse("documents:archive", args=[self.document.pk])
        )
        self.client.logout()
        self.login_with_company(CompanyMembership.Role.ADMIN)
        get_response = self.client.get(
            reverse("documents:archive", args=[self.document.pk])
        )

        self.assertEqual(operator_response.status_code, 403)
        self.assertEqual(get_response.status_code, 405)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, Document.Status.NEW)

    def test_mutations_require_a_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.users[CompanyMembership.Role.ADMIN])
        session = csrf_client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

        create_response = csrf_client.post(
            reverse("documents:create"),
            self.document_data(),
        )
        archive_response = csrf_client.post(
            reverse("documents:archive", args=[self.document.pk])
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(archive_response.status_code, 403)
        self.assertFalse(Document.objects.filter(title="Nouvel achat").exists())

    def test_navigation_and_actions_follow_the_active_role(self):
        self.login_with_company(CompanyMembership.Role.VIEWER)
        viewer_response = self.client.get(reverse("documents:list"))
        self.client.logout()
        self.login_with_company(CompanyMembership.Role.MANAGER)
        manager_response = self.client.get(reverse("documents:list"))

        self.assertContains(
            viewer_response,
            f'href="{reverse("documents:list")}"',
        )
        self.assertNotContains(viewer_response, reverse("documents:create"))
        self.assertNotContains(
            viewer_response,
            reverse("documents:update", args=[self.document.pk]),
        )
        self.assertNotContains(
            viewer_response,
            reverse("documents:archive", args=[self.document.pk]),
        )
        self.assertContains(manager_response, reverse("documents:create"))
        self.assertContains(
            manager_response,
            reverse("documents:update", args=[self.document.pk]),
        )
        self.assertContains(
            manager_response,
            reverse("documents:archive", args=[self.document.pk]),
        )
