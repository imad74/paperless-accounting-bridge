from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CompanyMembership
from accounts.services import ACTIVE_COMPANY_SESSION_KEY
from companies.models import Company


class CompanyMembershipViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="MEM-A", name="Membres A")
        cls.other_company = Company.objects.create(
            code="MEM-B",
            name="Membres B",
        )
        cls.users = {}
        cls.memberships = {}
        for role in CompanyMembership.Role.values:
            user = get_user_model().objects.create_user(
                username=f"membership-{role.lower()}",
                password="test-password",
                email=f"{role.lower()}@example.com",
            )
            membership = CompanyMembership.objects.create(
                user=user,
                company=cls.company,
                role=role,
            )
            cls.users[role] = user
            cls.memberships[role] = membership

        cls.candidate = get_user_model().objects.create_user(
            username="membership-candidate",
            password="test-password",
            email="candidate@example.com",
        )
        cls.inactive_candidate = get_user_model().objects.create_user(
            username="inactive-candidate",
            password="test-password",
            is_active=False,
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other-company-member",
            password="test-password",
        )
        cls.other_membership = CompanyMembership.objects.create(
            user=cls.other_user,
            company=cls.other_company,
            role=CompanyMembership.Role.ADMIN,
        )

    def login_with_company(self, user, company=None):
        self.client.force_login(user)
        session = self.client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = (company or self.company).pk
        session.save()

    def test_membership_list_requires_authentication(self):
        response = self.client.get(reverse("accounts:membership_list"))

        self.assertRedirects(
            response,
            "/admin/login/?next=/accounts/members/",
            fetch_redirect_response=False,
        )

    def test_admin_lists_only_members_of_the_active_company(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.get(reverse("accounts:membership_list"))

        self.assertEqual(response.status_code, 200)
        listed_ids = {membership.pk for membership in response.context["memberships"]}
        self.assertEqual(
            listed_ids,
            {membership.pk for membership in self.memberships.values()},
        )
        self.assertNotIn(self.other_membership.pk, listed_ids)

    def test_non_admin_roles_cannot_manage_members(self):
        for role in (
            CompanyMembership.Role.MANAGER,
            CompanyMembership.Role.OPERATOR,
            CompanyMembership.Role.VIEWER,
        ):
            with self.subTest(role=role):
                self.login_with_company(self.users[role])

                response = self.client.get(reverse("accounts:membership_list"))

                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_non_admin_cannot_create_update_or_delete_memberships(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        self.login_with_company(self.users[CompanyMembership.Role.MANAGER])

        create_response = self.client.get(reverse("accounts:membership_create"))
        update_response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {"role": CompanyMembership.Role.OPERATOR, "active": "on"},
        )
        delete_response = self.client.post(
            reverse("accounts:membership_delete", args=[membership.pk])
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(CompanyMembership.objects.filter(pk=membership.pk).exists())

    def test_user_without_membership_is_sent_to_company_selector(self):
        self.client.force_login(self.candidate)

        response = self.client.get(reverse("accounts:membership_list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Faccounts%2Fmembers%2F",
            fetch_redirect_response=False,
        )

    def test_inactive_admin_membership_gives_no_access(self):
        admin_user = self.users[CompanyMembership.Role.ADMIN]
        CompanyMembership.objects.filter(
            pk=self.memberships[CompanyMembership.Role.ADMIN].pk
        ).update(active=False)
        self.login_with_company(admin_user)

        response = self.client.get(reverse("accounts:membership_list"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:company_select')}?next=%2Faccounts%2Fmembers%2F",
            fetch_redirect_response=False,
        )

    def test_create_form_only_offers_active_users_not_already_members(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.get(reverse("accounts:membership_create"))

        queryset = response.context["form"].fields["user"].queryset
        self.assertIn(self.candidate, queryset)
        self.assertNotIn(self.inactive_candidate, queryset)
        self.assertNotIn(self.users[CompanyMembership.Role.VIEWER], queryset)

    def test_admin_can_add_an_existing_user(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_create"),
            {
                "user": self.candidate.pk,
                "role": CompanyMembership.Role.OPERATOR,
                "active": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:membership_list"),
            fetch_redirect_response=False,
        )
        membership = CompanyMembership.objects.get(
            user=self.candidate,
            company=self.company,
        )
        self.assertEqual(membership.role, CompanyMembership.Role.OPERATOR)
        self.assertTrue(membership.active)

    def test_duplicate_membership_is_rejected_by_the_form(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_create"),
            {
                "user": self.users[CompanyMembership.Role.VIEWER].pk,
                "role": CompanyMembership.Role.VIEWER,
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("user"))
        self.assertEqual(
            CompanyMembership.objects.filter(
                user=self.users[CompanyMembership.Role.VIEWER],
                company=self.company,
            ).count(),
            1,
        )

    def test_admin_can_change_role_and_suspend_membership(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])
        membership = self.memberships[CompanyMembership.Role.VIEWER]

        response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {
                "role": CompanyMembership.Role.OPERATOR,
                "active": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:membership_list"),
            fetch_redirect_response=False,
        )
        membership.refresh_from_db()
        self.assertEqual(membership.role, CompanyMembership.Role.OPERATOR)
        self.assertFalse(membership.active)

    def test_admin_can_reactivate_membership(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        CompanyMembership.objects.filter(pk=membership.pk).update(active=False)
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {
                "role": CompanyMembership.Role.VIEWER,
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertTrue(membership.active)

    def test_last_active_admin_cannot_be_demoted(self):
        membership = self.memberships[CompanyMembership.Role.ADMIN]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {
                "role": CompanyMembership.Role.MANAGER,
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CompanyMembership.LAST_ACTIVE_ADMIN_ERROR)
        membership.refresh_from_db()
        self.assertEqual(membership.role, CompanyMembership.Role.ADMIN)
        self.assertTrue(membership.active)

    def test_last_active_admin_cannot_be_suspended(self):
        membership = self.memberships[CompanyMembership.Role.ADMIN]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {
                "role": CompanyMembership.Role.ADMIN,
                "active": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CompanyMembership.LAST_ACTIVE_ADMIN_ERROR)
        membership.refresh_from_db()
        self.assertTrue(membership.active)

    def test_last_active_admin_cannot_be_deleted(self):
        membership = self.memberships[CompanyMembership.Role.ADMIN]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_delete", args=[membership.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CompanyMembership.LAST_ACTIVE_ADMIN_ERROR)
        self.assertTrue(CompanyMembership.objects.filter(pk=membership.pk).exists())

    def test_second_active_admin_allows_first_admin_to_be_demoted(self):
        CompanyMembership.objects.filter(
            pk=self.memberships[CompanyMembership.Role.MANAGER].pk
        ).update(role=CompanyMembership.Role.ADMIN)
        membership = self.memberships[CompanyMembership.Role.ADMIN]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_update", args=[membership.pk]),
            {
                "role": CompanyMembership.Role.MANAGER,
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertEqual(membership.role, CompanyMembership.Role.MANAGER)

    def test_admin_can_remove_a_non_admin_membership(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        response = self.client.post(
            reverse("accounts:membership_delete", args=[membership.pk])
        )

        self.assertRedirects(
            response,
            reverse("accounts:membership_list"),
            fetch_redirect_response=False,
        )
        self.assertFalse(CompanyMembership.objects.filter(pk=membership.pk).exists())

    def test_cross_company_membership_objects_return_404(self):
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        update_response = self.client.get(
            reverse(
                "accounts:membership_update",
                args=[self.other_membership.pk],
            )
        )
        delete_response = self.client.get(
            reverse(
                "accounts:membership_delete",
                args=[self.other_membership.pk],
            )
        )

        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)

    def test_membership_mutations_reject_non_post_methods(self):
        membership = self.memberships[CompanyMembership.Role.VIEWER]
        self.login_with_company(self.users[CompanyMembership.Role.ADMIN])

        create_response = self.client.put(
            reverse("accounts:membership_create"),
            data={"user": self.candidate.pk},
            content_type="application/json",
        )
        update_response = self.client.put(
            reverse("accounts:membership_update", args=[membership.pk]),
            data={"role": CompanyMembership.Role.OPERATOR},
            content_type="application/json",
        )
        delete_response = self.client.delete(
            reverse("accounts:membership_delete", args=[membership.pk])
        )

        self.assertEqual(create_response.status_code, 405)
        self.assertEqual(update_response.status_code, 405)
        self.assertEqual(delete_response.status_code, 405)
        self.assertTrue(CompanyMembership.objects.filter(pk=membership.pk).exists())

    def test_membership_mutation_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.users[CompanyMembership.Role.ADMIN])
        session = csrf_client.session
        session[ACTIVE_COMPANY_SESSION_KEY] = self.company.pk
        session.save()

        response = csrf_client.post(
            reverse("accounts:membership_create"),
            {
                "user": self.candidate.pk,
                "role": CompanyMembership.Role.VIEWER,
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CompanyMembership.objects.filter(
                user=self.candidate,
                company=self.company,
            ).exists()
        )
