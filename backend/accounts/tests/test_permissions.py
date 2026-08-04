from django.test import SimpleTestCase

from accounts.models import CompanyMembership
from accounts.permissions import CompanyPermission, role_has_permission


class CompanyPermissionMatrixTests(SimpleTestCase):
    def test_permission_matrix_matches_release_003(self):
        expected_permissions = {
            CompanyMembership.Role.ADMIN: {
                CompanyPermission.VIEW_COMPANY,
                CompanyPermission.CHANGE_COMPANY,
                CompanyPermission.MANAGE_MEMBERS,
                CompanyPermission.VIEW_DOCUMENT_TYPES,
                CompanyPermission.MANAGE_DOCUMENT_TYPES,
                CompanyPermission.VIEW_DOCUMENTS,
                CompanyPermission.CHANGE_DOCUMENTS,
                CompanyPermission.ARCHIVE_DOCUMENTS,
            },
            CompanyMembership.Role.MANAGER: {
                CompanyPermission.VIEW_COMPANY,
                CompanyPermission.VIEW_DOCUMENT_TYPES,
                CompanyPermission.MANAGE_DOCUMENT_TYPES,
                CompanyPermission.VIEW_DOCUMENTS,
                CompanyPermission.CHANGE_DOCUMENTS,
                CompanyPermission.ARCHIVE_DOCUMENTS,
            },
            CompanyMembership.Role.OPERATOR: {
                CompanyPermission.VIEW_COMPANY,
                CompanyPermission.VIEW_DOCUMENT_TYPES,
                CompanyPermission.VIEW_DOCUMENTS,
                CompanyPermission.CHANGE_DOCUMENTS,
            },
            CompanyMembership.Role.VIEWER: {
                CompanyPermission.VIEW_COMPANY,
                CompanyPermission.VIEW_DOCUMENT_TYPES,
                CompanyPermission.VIEW_DOCUMENTS,
            },
        }
        all_permissions = {
            CompanyPermission.VIEW_COMPANY,
            CompanyPermission.CHANGE_COMPANY,
            CompanyPermission.MANAGE_MEMBERS,
            CompanyPermission.VIEW_DOCUMENT_TYPES,
            CompanyPermission.MANAGE_DOCUMENT_TYPES,
            CompanyPermission.VIEW_DOCUMENTS,
            CompanyPermission.CHANGE_DOCUMENTS,
            CompanyPermission.ARCHIVE_DOCUMENTS,
        }

        for role, allowed_permissions in expected_permissions.items():
            with self.subTest(role=role):
                actual_permissions = {
                    permission
                    for permission in all_permissions
                    if role_has_permission(role, permission)
                }
                self.assertEqual(actual_permissions, allowed_permissions)

    def test_unknown_role_has_no_permission(self):
        self.assertFalse(
            role_has_permission("UNKNOWN", CompanyPermission.VIEW_COMPANY)
        )
