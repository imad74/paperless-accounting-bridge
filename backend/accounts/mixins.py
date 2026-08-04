from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse

from .permissions import role_has_permission
from .services import resolve_active_company_membership


class ActiveCompanyRequiredMixin(LoginRequiredMixin):
    """Require and expose a valid active company for a business view."""

    def has_company_permission(self) -> bool:
        return True

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        membership = resolve_active_company_membership(request)
        if membership is None:
            query = urlencode({"next": request.get_full_path()})
            return HttpResponseRedirect(
                f"{reverse('accounts:company_select')}?{query}"
            )

        self.active_company_membership = membership
        self.active_company = membership.company
        request.active_company_membership = membership
        request.active_company = membership.company

        if not self.has_company_permission():
            raise PermissionDenied("Vous n’avez pas la permission requise.")

        return super().dispatch(request, *args, **kwargs)


class CompanyPermissionRequiredMixin(ActiveCompanyRequiredMixin):
    """Check a centralized permission against the active membership role."""

    required_company_permission = None

    def has_company_permission(self) -> bool:
        if self.required_company_permission is None:
            raise ImproperlyConfigured(
                "required_company_permission must be configured."
            )
        return role_has_permission(
            self.active_company_membership.role,
            self.required_company_permission,
        )


class ActiveCompanyQuerysetMixin:
    """Restrict object lookup to the active company before retrieval."""

    company_lookup = "company_id"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(
            **{self.company_lookup: self.active_company.pk}
        )


class ApplicationAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict global application operations to active superusers."""

    def test_func(self):
        return self.request.user.is_active and self.request.user.is_superuser
