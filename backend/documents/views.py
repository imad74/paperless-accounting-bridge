from django.views.generic import ListView

from accounts.mixins import (
    ActiveCompanyQuerysetMixin,
    CompanyPermissionRequiredMixin,
)
from accounts.permissions import CompanyPermission

from .models import Document


class DocumentListView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    ListView,
):
    model = Document
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS
