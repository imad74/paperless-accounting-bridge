from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company
from documents.models import Document, DocumentType
from documents.views import DocumentListView


class DocumentListIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="document-viewer",
            password="test-password",
        )
        cls.company = Company.objects.create(code="DOC-A", name="Documents A")
        cls.other_company = Company.objects.create(
            code="DOC-B",
            name="Documents B",
        )
        cls.membership = CompanyMembership.objects.create(
            user=cls.user,
            company=cls.company,
            role=CompanyMembership.Role.VIEWER,
        )
        cls.document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        cls.document = Document.objects.create(
            number="FN-DOC-A-000001",
            title="Document autorisé",
            company=cls.company,
            document_type=cls.document_type,
            original_filename="allowed.pdf",
            stored_filename="allowed.pdf",
            document_date=date(2026, 8, 4),
        )
        cls.other_document = Document.objects.create(
            number="FN-DOC-B-000001",
            title="Document interdit",
            company=cls.other_company,
            document_type=cls.document_type,
            original_filename="forbidden.pdf",
            stored_filename="forbidden.pdf",
            document_date=date(2026, 8, 4),
        )

    def make_request(self, user=None, company=None):
        request = RequestFactory().get("/documents/")
        request.user = user or self.user
        request.session = {
            ACTIVE_COMPANY_SESSION_KEY: (company or self.company).pk
        }
        return request

    def test_queryset_only_contains_active_company_documents(self):
        response = DocumentListView.as_view()(self.make_request())

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context_data["object_list"],
            [self.document],
        )

    def test_anonymous_user_is_redirected_to_login(self):
        request = self.make_request(user=AnonymousUser())
        request.session = {}

        response = DocumentListView.as_view()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            "/admin/login/?next=/documents/",
        )

    def test_inactive_membership_cannot_list_documents(self):
        self.membership.active = False
        self.membership.save(update_fields=["active"])

        response = DocumentListView.as_view()(self.make_request())

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/accounts/company/select/?next="))
