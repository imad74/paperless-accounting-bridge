from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from documents.forms import DocumentForm, DocumentTypeForm
from documents.models import Document, DocumentType


class DocumentTypeModelAndFormTests(TestCase):
    def test_identifiers_are_normalized_on_save(self):
        document_type = DocumentType.objects.create(
            code="  inv ",
            name="Facture fournisseur",
            prefix=" fn ",
        )

        self.assertEqual(document_type.code, "INV")
        self.assertEqual(document_type.prefix, "FN")

    def test_code_is_unique_without_case_sensitivity(self):
        DocumentType.objects.create(code="INV", name="Facture", prefix="FN")
        form = DocumentTypeForm(
            data={
                "code": " inv ",
                "name": "Autre facture",
                "prefix": "AF",
                "description": "",
                "yearly_reset": "on",
                "active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_prefix_is_unique_without_case_sensitivity(self):
        DocumentType.objects.create(code="INV", name="Facture", prefix="FN")
        form = DocumentTypeForm(
            data={
                "code": "CRN",
                "name": "Avoir",
                "prefix": " fn ",
                "description": "",
                "yearly_reset": "on",
                "active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("prefix", form.errors)

    def test_used_document_type_cannot_be_deleted(self):
        company = Company.objects.create(code="TYPE-DOC", name="Documents")
        document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        Document.objects.create(
            number="FN-TYPE-DOC-000001",
            title="Facture protégée",
            company=company,
            document_type=document_type,
            original_filename="invoice.pdf",
            stored_filename="invoice.pdf",
            document_date=date(2026, 8, 4),
        )

        with self.assertRaises(ProtectedError):
            document_type.delete()

    def test_inactive_type_is_not_available_for_a_new_document(self):
        active_type = DocumentType.objects.create(
            code="ACT",
            name="Type actif",
            prefix="ACT",
        )
        inactive_type = DocumentType.objects.create(
            code="INA",
            name="Type inactif",
            prefix="INA",
            active=False,
        )

        queryset = DocumentForm().fields["document_type"].queryset

        self.assertIn(active_type, queryset)
        self.assertNotIn(inactive_type, queryset)

    def test_existing_document_keeps_its_inactive_type_available(self):
        company = Company.objects.create(code="TYPE-EDIT", name="Modification")
        document_type = DocumentType.objects.create(
            code="OLD",
            name="Ancien type",
            prefix="OLD",
            active=False,
        )
        document = Document.objects.create(
            number="OLD-TYPE-EDIT-000001",
            title="Document existant",
            company=company,
            document_type=document_type,
            original_filename="old.pdf",
            stored_filename="old.pdf",
            document_date=date(2026, 8, 4),
        )

        queryset = DocumentForm(instance=document).fields[
            "document_type"
        ].queryset

        self.assertIn(document_type, queryset)


class DocumentTypeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="TYPE-A", name="Types A")
        cls.users = {}
        cls.memberships = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(
                username=f"type-{role.lower()}",
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
            username="type-no-membership",
            password="test-password",
        )
        cls.active_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        cls.inactive_type = DocumentType.objects.create(
            code="CRN",
            name="Avoir",
            prefix="AV",
            active=False,
        )

    def login_with_company(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

    def document_type_data(self, **overrides):
        data = {
            "code": "PO",
            "name": "Bon de commande",
            "prefix": "BC",
            "description": "Commandes fournisseurs",
            "yearly_reset": "on",
            "active": "on",
        }
        data.update(overrides)
        return data

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("document_types:list"))

        self.assertRedirects(
            response,
            f"/admin/login/?next={reverse('document_types:list')}",
            fetch_redirect_response=False,
        )

    def test_all_roles_can_view_document_types(self):
        for role in CompanyMembership.Role.values:
            with self.subTest(role=role):
                self.client.logout()
                self.login_with_company(self.users[role])

                response = self.client.get(reverse("document_types:list"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.active_type.name)

    def test_user_without_membership_is_sent_to_company_selector(self):
        self.client.force_login(self.user_without_membership)

        response = self.client.get(reverse("document_types:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fdocument-types%2F",
            fetch_redirect_response=False,
        )

    def test_inactive_membership_cannot_view_document_types(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        CompanyMembership.objects.filter(pk=membership.pk).update(active=False)
        self.login_with_company(self.users[CompanyMembership.Role.VIEWER])

        response = self.client.get(reverse("document_types:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fdocument-types%2F",
            fetch_redirect_response=False,
        )

    def test_admin_and_manager_can_open_management_forms(self):
        for role in (
            CompanyMembership.Role.ADMIN,
            CompanyMembership.Role.MANAGER,
        ):
            with self.subTest(role=role):
                self.client.logout()
                self.login_with_company(self.users[role])

                create_response = self.client.get(
                    reverse("document_types:create")
                )
                update_response = self.client.get(
                    reverse(
                        "document_types:update",
                        args=[self.active_type.pk],
                    )
                )

                self.assertEqual(create_response.status_code, 200)
                self.assertEqual(update_response.status_code, 200)

    def test_operator_and_viewer_cannot_manage_document_types(self):
        for role in (
            CompanyMembership.Role.OPERATOR,
            CompanyMembership.Role.VIEWER,
        ):
            with self.subTest(role=role):
                self.client.logout()
                self.login_with_company(self.users[role])

                create_response = self.client.get(
                    reverse("document_types:create")
                )
                update_response = self.client.post(
                    reverse(
                        "document_types:update",
                        args=[self.active_type.pk],
                    ),
                    self.document_type_data(),
                )
                toggle_response = self.client.post(
                    reverse(
                        "document_types:toggle_active",
                        args=[self.active_type.pk],
                    )
                )

                self.assertEqual(create_response.status_code, 403)
                self.assertEqual(update_response.status_code, 403)
                self.assertEqual(toggle_response.status_code, 403)

        self.active_type.refresh_from_db()
        self.assertTrue(self.active_type.active)

    def test_management_permission_uses_the_role_of_the_active_company(self):
        other_company = Company.objects.create(
            code="TYPE-B",
            name="Types B",
        )
        admin_user = self.users[CompanyMembership.Role.ADMIN]
        CompanyMembership.objects.create(
            user=admin_user,
            company=other_company,
            role=CompanyMembership.Role.VIEWER,
        )
        self.login_with_company(admin_user)
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = other_company.pk
        session.save()

        response = self.client.post(
            reverse("document_types:create"),
            self.document_type_data(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(DocumentType.objects.filter(code="PO").exists())

    def test_admin_can_create_a_normalized_document_type(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("document_types:create"),
            self.document_type_data(code="  po ", prefix=" bc "),
            follow=True,
        )

        self.assertRedirects(response, reverse("document_types:list"))
        document_type = DocumentType.objects.get(code="PO")
        self.assertEqual(document_type.prefix, "BC")
        self.assertContains(response, "Type documentaire créé avec succès.")

    def test_manager_can_update_a_document_type(self):
        self.login_with_company(self.users[CompanyMembership.Role.MANAGER])

        response = self.client.post(
            reverse("document_types:update", args=[self.active_type.pk]),
            self.document_type_data(
                code=" inv ",
                name="Facture fournisseur",
                prefix=" fac ",
            ),
            follow=True,
        )

        self.assertRedirects(response, reverse("document_types:list"))
        self.active_type.refresh_from_db()
        self.assertEqual(self.active_type.name, "Facture fournisseur")
        self.assertEqual(self.active_type.prefix, "FAC")
        self.assertContains(response, "Type documentaire modifié avec succès.")

    def test_duplicate_validation_errors_are_displayed(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("document_types:create"),
            self.document_type_data(code=" inv "),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Un type documentaire avec ce code existe déjà.",
        )

    def test_manager_can_deactivate_and_reactivate_a_type(self):
        self.login_with_company(self.users[CompanyMembership.Role.MANAGER])
        url = reverse(
            "document_types:toggle_active",
            args=[self.active_type.pk],
        )

        deactivate_response = self.client.post(url, follow=True)
        self.active_type.refresh_from_db()
        self.assertFalse(self.active_type.active)
        self.assertContains(deactivate_response, "a été désactivé")

        reactivate_response = self.client.post(url, follow=True)
        self.active_type.refresh_from_db()
        self.assertTrue(self.active_type.active)
        self.assertContains(reactivate_response, "a été activé")

    def test_toggle_rejects_get_requests(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.get(
            reverse(
                "document_types:toggle_active",
                args=[self.active_type.pk],
            )
        )

        self.assertEqual(response.status_code, 405)
        self.active_type.refresh_from_db()
        self.assertTrue(self.active_type.active)

    def test_mutations_require_a_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.users[CompanyMembership.Role.ADMIN])
        session = csrf_client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

        create_response = csrf_client.post(
            reverse("document_types:create"),
            self.document_type_data(),
        )
        toggle_response = csrf_client.post(
            reverse(
                "document_types:toggle_active",
                args=[self.active_type.pk],
            )
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(toggle_response.status_code, 403)
        self.assertFalse(DocumentType.objects.filter(code="PO").exists())

    def test_list_supports_search_and_status_filtering(self):
        self.login_with_company(self.users[CompanyMembership.Role.VIEWER])

        search_response = self.client.get(
            reverse("document_types:list"),
            {"q": "fact"},
        )
        inactive_response = self.client.get(
            reverse("document_types:list"),
            {"status": "inactive"},
        )

        self.assertContains(search_response, self.active_type.name)
        self.assertNotContains(search_response, self.inactive_type.name)
        self.assertContains(inactive_response, self.inactive_type.name)
        self.assertNotContains(inactive_response, self.active_type.name)

    def test_pagination_preserves_search_and_status_filters(self):
        for index in range(21):
            DocumentType.objects.create(
                code=f"PG{index:02d}",
                name=f"Paginer {index:02d}",
                prefix=f"P{index:02d}",
            )
        self.login_with_company(self.users[CompanyMembership.Role.VIEWER])

        response = self.client.get(
            f"{reverse('document_types:list')}?q=Paginer&status=active"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertContains(
            response,
            "?page=2&amp;q=Paginer&amp;status=active",
        )

    def test_read_only_roles_do_not_see_management_actions(self):
        self.login_with_company(self.users[CompanyMembership.Role.VIEWER])

        response = self.client.get(reverse("document_types:list"))

        self.assertNotContains(response, reverse("document_types:create"))
        self.assertNotContains(
            response,
            reverse("document_types:update", args=[self.active_type.pk]),
        )
