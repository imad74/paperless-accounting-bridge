from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company


class CompanyViewPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="PERM-A", name="Permissions A")
        cls.other_company = Company.objects.create(
            code="PERM-B",
            name="Permissions B",
        )
        cls.users = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(
                username=f"company-{role.lower()}",
                password="test-password",
            )
            CompanyMembership.objects.create(
                user=user,
                company=cls.company,
                role=role,
            )
            cls.users[role] = user

        cls.other_admin = get_user_model().objects.create_user(
            username="other-company-admin",
            password="test-password",
        )
        CompanyMembership.objects.create(
            user=cls.other_admin,
            company=cls.other_company,
            role=CompanyMembership.Role.ADMIN,
        )

    def login_with_company(self, user, company=None):
        self.client.force_login(user)
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = (company or self.company).pk
        session.save()

    def test_company_list_requires_authentication(self):
        response = self.client.get(reverse("companies:list"))

        self.assertRedirects(
            response,
            "/admin/login/?next=/companies/",
            fetch_redirect_response=False,
        )

    def test_all_roles_can_list_only_their_accessible_companies(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.login_with_company(user)
                response = self.client.get(reverse("companies:list"))

                self.assertEqual(response.status_code, 200)
                self.assertQuerySetEqual(
                    response.context["companies"],
                    [self.company],
                )
                self.client.logout()

    def test_only_admin_role_can_open_company_update(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.login_with_company(user)
                response = self.client.get(
                    reverse("companies:update", args=[self.company.pk])
                )

                expected_status = (
                    200 if role == CompanyMembership.Role.ADMIN else 403
                )
                self.assertEqual(response.status_code, expected_status)
                self.client.logout()

    def test_active_admin_cannot_load_another_company_object(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.get(
            reverse("companies:update", args=[self.other_company.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_gives_no_business_access(self):
        user = self.users[CompanyMembership.Role.VIEWER]
        CompanyMembership.objects.filter(user=user, company=self.company).update(
            active=False
        )
        self.login_with_company(user)

        response = self.client.get(reverse("companies:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fcompanies%2F",
            fetch_redirect_response=False,
        )
        self.assertNotIn(ACTIVE_COMPANY_SESSION_KEY, self.client.session)

    def test_user_without_membership_is_sent_to_selector(self):
        user = get_user_model().objects.create_user(
            username="without-company",
            password="test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("companies:list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Fcompanies%2F",
            fetch_redirect_response=False,
        )

    def test_only_superuser_can_create_a_company(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])
        denied_response = self.client.get(reverse("companies:create"))
        self.assertEqual(denied_response.status_code, 403)

        superuser = get_user_model().objects.create_superuser(
            username="application-admin",
            password="test-password",
            email="admin@example.com",
        )
        self.client.force_login(superuser)
        allowed_response = self.client.get(reverse("companies:create"))
        self.assertEqual(allowed_response.status_code, 200)

    def test_created_company_is_assigned_to_its_superuser(self):
        superuser = get_user_model().objects.create_superuser(
            username="company-creator",
            password="test-password",
            email="creator@example.com",
        )
        self.client.force_login(superuser)

        response = self.client.post(
            reverse("companies:create"),
            {
                "code": "CREATED",
                "name": "Société créée",
                "country": "Maroc",
                "active": "on",
            },
        )

        company = Company.objects.get(code="CREATED")
        membership = CompanyMembership.objects.get(
            user=superuser,
            company=company,
        )
        self.assertRedirects(
            response,
            reverse("companies:list"),
            fetch_redirect_response=False,
        )
        self.assertEqual(membership.role, CompanyMembership.Role.ADMIN)
        self.assertTrue(membership.active)
        self.assertEqual(
            self.client.session[ACTIVE_COMPANY_SESSION_KEY],
            company.pk,
        )
