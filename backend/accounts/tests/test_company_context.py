from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import (
    ACTIVE_COMPANY_SESSION_KEY,
    resolve_active_company_membership,
    set_active_company,
)
from companies.models import Company


class CompanyContextServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="context-user",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other-context-user",
            password="test-password",
        )
        cls.company_a = Company.objects.create(code="CTX-A", name="Context A")
        cls.company_b = Company.objects.create(code="CTX-B", name="Context B")
        cls.membership_a = CompanyMembership.objects.create(
            user=cls.user,
            company=cls.company_a,
            role=CompanyMembership.Role.ADMIN,
        )

    def make_request(self, user=None, session=None):
        request = RequestFactory().get("/")
        request.user = user or self.user
        request.session = session if session is not None else {}
        return request

    def test_single_available_company_is_selected_automatically(self):
        request = self.make_request()

        membership = resolve_active_company_membership(request)

        self.assertEqual(membership, self.membership_a)
        self.assertEqual(
            request.session[ACTIVE_COMPANY_SESSION_KEY],
            self.company_a.pk,
        )

    def test_multiple_companies_require_an_explicit_selection(self):
        CompanyMembership.objects.create(
            user=self.user,
            company=self.company_b,
            role=CompanyMembership.Role.VIEWER,
        )
        request = self.make_request()

        membership = resolve_active_company_membership(request)

        self.assertIsNone(membership)
        self.assertNotIn(ACTIVE_COMPANY_SESSION_KEY, request.session)

    def test_session_company_is_revalidated_against_memberships(self):
        CompanyMembership.objects.create(
            user=self.user,
            company=self.company_b,
            role=CompanyMembership.Role.VIEWER,
        )
        request = self.make_request(
            session={ACTIVE_COMPANY_SESSION_KEY: self.company_b.pk}
        )

        membership = resolve_active_company_membership(request)

        self.assertEqual(membership.company, self.company_b)

    def test_inactive_membership_clears_the_session(self):
        self.membership_a.active = False
        self.membership_a.save(update_fields=["active"])
        request = self.make_request(
            session={ACTIVE_COMPANY_SESSION_KEY: self.company_a.pk}
        )

        membership = resolve_active_company_membership(request)

        self.assertIsNone(membership)
        self.assertNotIn(ACTIVE_COMPANY_SESSION_KEY, request.session)

    def test_inactive_company_clears_the_session(self):
        self.company_a.active = False
        self.company_a.save(update_fields=["active"])
        request = self.make_request(
            session={ACTIVE_COMPANY_SESSION_KEY: self.company_a.pk}
        )

        membership = resolve_active_company_membership(request)

        self.assertIsNone(membership)
        self.assertNotIn(ACTIVE_COMPANY_SESSION_KEY, request.session)

    def test_another_users_company_cannot_be_selected(self):
        CompanyMembership.objects.create(
            user=self.other_user,
            company=self.company_b,
            role=CompanyMembership.Role.ADMIN,
        )
        request = self.make_request()

        with self.assertRaises(Http404):
            set_active_company(request, self.company_b.pk)


class CompanySelectionViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="selector-user",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="selector-other",
            password="test-password",
        )
        cls.company_a = Company.objects.create(code="SEL-A", name="Sélection A")
        cls.company_b = Company.objects.create(code="SEL-B", name="Sélection B")
        cls.other_company = Company.objects.create(
            code="SEL-X",
            name="Sélection interdite",
        )
        cls.membership_a = CompanyMembership.objects.create(
            user=cls.user,
            company=cls.company_a,
            role=CompanyMembership.Role.ADMIN,
        )
        cls.membership_b = CompanyMembership.objects.create(
            user=cls.user,
            company=cls.company_b,
            role=CompanyMembership.Role.VIEWER,
        )
        cls.other_membership = CompanyMembership.objects.create(
            user=cls.other_user,
            company=cls.other_company,
            role=CompanyMembership.Role.ADMIN,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_selector_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("accounts:company_select"))

        self.assertRedirects(
            response,
            f"/admin/login/?next={reverse('accounts:company_select')}",
            fetch_redirect_response=False,
        )

    def test_selector_only_lists_available_companies(self):
        response = self.client.get(reverse("accounts:company_select"))

        self.assertContains(response, self.company_a.name)
        self.assertContains(response, self.company_b.name)
        self.assertNotContains(response, self.other_company.name)

    def test_post_sets_the_active_company_and_keeps_safe_next(self):
        response = self.client.post(
            reverse("accounts:company_select"),
            {
                "membership": self.membership_b.pk,
                "next": reverse("companies:list"),
            },
        )

        self.assertRedirects(
            response,
            reverse("companies:list"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session[ACTIVE_COMPANY_SESSION_KEY],
            self.company_b.pk,
        )

    def test_post_rejects_another_users_membership(self):
        response = self.client.post(
            reverse("accounts:company_select"),
            {"membership": self.other_membership.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "membership",
            "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        )
        self.assertNotIn(ACTIVE_COMPANY_SESSION_KEY, self.client.session)

    def test_external_next_url_is_not_followed(self):
        response = self.client.post(
            reverse("accounts:company_select"),
            {
                "membership": self.membership_a.pk,
                "next": "https://example.invalid/steal-session",
            },
        )

        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )


class ActiveCompanyViewIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="home-user",
            password="test-password",
        )
        cls.company_a = Company.objects.create(code="HOME-A", name="Accueil A")
        cls.company_b = Company.objects.create(code="HOME-B", name="Accueil B")
        CompanyMembership.objects.create(
            user=cls.user,
            company=cls.company_a,
            role=CompanyMembership.Role.VIEWER,
        )

    def test_health_endpoint_remains_public(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "paperless-accounting-bridge"},
        )

    def test_home_requires_authentication(self):
        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            "/admin/login/?next=/",
            fetch_redirect_response=False,
        )

    def test_home_auto_selects_a_single_company(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.company_a.name)
        self.assertEqual(
            self.client.session[ACTIVE_COMPANY_SESSION_KEY],
            self.company_a.pk,
        )

    def test_home_redirects_to_selector_when_multiple_companies_exist(self):
        CompanyMembership.objects.create(
            user=self.user,
            company=self.company_b,
            role=CompanyMembership.Role.VIEWER,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2F",
            fetch_redirect_response=False,
        )
