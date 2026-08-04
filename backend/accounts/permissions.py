from .models import CompanyMembership


class CompanyPermission:
    """Permission names used by company-scoped business views."""

    VIEW_COMPANY = "company.view"
    CHANGE_COMPANY = "company.change"
    MANAGE_MEMBERS = "members.manage"
    VIEW_DOCUMENT_TYPES = "document_types.view"
    MANAGE_DOCUMENT_TYPES = "document_types.manage"
    VIEW_DOCUMENTS = "documents.view"
    CHANGE_DOCUMENTS = "documents.change"
    ARCHIVE_DOCUMENTS = "documents.archive"


ROLE_PERMISSIONS = {
    CompanyMembership.Role.ADMIN: frozenset(
        {
            CompanyPermission.VIEW_COMPANY,
            CompanyPermission.CHANGE_COMPANY,
            CompanyPermission.MANAGE_MEMBERS,
            CompanyPermission.VIEW_DOCUMENT_TYPES,
            CompanyPermission.MANAGE_DOCUMENT_TYPES,
            CompanyPermission.VIEW_DOCUMENTS,
            CompanyPermission.CHANGE_DOCUMENTS,
            CompanyPermission.ARCHIVE_DOCUMENTS,
        }
    ),
    CompanyMembership.Role.MANAGER: frozenset(
        {
            CompanyPermission.VIEW_COMPANY,
            CompanyPermission.VIEW_DOCUMENT_TYPES,
            CompanyPermission.MANAGE_DOCUMENT_TYPES,
            CompanyPermission.VIEW_DOCUMENTS,
            CompanyPermission.CHANGE_DOCUMENTS,
            CompanyPermission.ARCHIVE_DOCUMENTS,
        }
    ),
    CompanyMembership.Role.OPERATOR: frozenset(
        {
            CompanyPermission.VIEW_COMPANY,
            CompanyPermission.VIEW_DOCUMENT_TYPES,
            CompanyPermission.VIEW_DOCUMENTS,
            CompanyPermission.CHANGE_DOCUMENTS,
        }
    ),
    CompanyMembership.Role.VIEWER: frozenset(
        {
            CompanyPermission.VIEW_COMPANY,
            CompanyPermission.VIEW_DOCUMENT_TYPES,
            CompanyPermission.VIEW_DOCUMENTS,
        }
    ),
}


def role_has_permission(role: str, permission: str) -> bool:
    """Return whether an application role grants a company permission."""

    return permission in ROLE_PERMISSIONS.get(role, frozenset())
