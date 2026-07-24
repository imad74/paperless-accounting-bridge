from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import CompanyMembership
from companies.models import Company


class CompanyMembershipModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="operator",
            password="test-password",
        )
        cls.company = Company.objects.create(
            code="ACME",
            name="Acme SARL",
        )

    def test_defaults_to_active_viewer_membership(self):
        membership = CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
        )

        self.assertEqual(membership.role, CompanyMembership.Role.VIEWER)
        self.assertTrue(membership.active)
        self.assertIsNotNone(membership.created_at)
        self.assertIsNotNone(membership.updated_at)

    def test_user_and_company_pair_is_unique(self):
        CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompanyMembership.objects.create(
                    user=self.user,
                    company=self.company,
                    role=CompanyMembership.Role.ADMIN,
                )

    def test_role_choices_are_validated(self):
        membership = CompanyMembership(
            user=self.user,
            company=self.company,
            role="INVALID",
        )

        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_all_declared_roles_can_be_saved(self):
        second_company = Company.objects.create(
            code="BETA",
            name="Beta SARL",
        )

        for index, role in enumerate(CompanyMembership.Role.values):
            user = get_user_model().objects.create_user(
                username=f"member-{index}",
                password="test-password",
            )
            membership = CompanyMembership.objects.create(
                user=user,
                company=second_company,
                role=role,
            )
            self.assertEqual(membership.role, role)

    def test_inactive_membership_is_excluded_from_active_queryset(self):
        CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            active=False,
        )

        self.assertFalse(
            CompanyMembership.objects.filter(
                user=self.user,
                company=self.company,
                active=True,
            ).exists()
        )

    def test_string_representation_contains_user_company_and_role(self):
        membership = CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            role=CompanyMembership.Role.ADMIN,
        )

        self.assertEqual(
            str(membership),
            "operator — ACME - Acme SARL (Administrateur)",
        )
