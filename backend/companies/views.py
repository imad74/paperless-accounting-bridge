from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
)

from accounts.mixins import (
    ActiveCompanyQuerysetMixin,
    ApplicationAdminRequiredMixin,
    CompanyPermissionRequiredMixin,
)
from accounts.models import CompanyMembership
from accounts.permissions import CompanyPermission, role_has_permission
from accounts.services import ACTIVE_COMPANY_SESSION_KEY, clear_active_company

from .forms import CompanyForm
from .models import Company


class CompanyListView(CompanyPermissionRequiredMixin, ListView):
    model = Company
    template_name = "companies/list.html"
    context_object_name = "companies"
    paginate_by = 15
    required_company_permission = CompanyPermission.VIEW_COMPANY

    def get_queryset(self):
        queryset = Company.objects.filter(
            memberships__user=self.request.user,
            memberships__active=True,
        ).distinct()
        search = self.request.GET.get("q")
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(city__icontains=search)
                | Q(contact__icontains=search)
                | Q(email__icontains=search)
            )
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage_active_company"] = role_has_permission(
            self.active_company_membership.role,
            CompanyPermission.CHANGE_COMPANY,
        )
        return context


class CompanyCreateView(ApplicationAdminRequiredMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = "companies/form.html"
    success_url = reverse_lazy("companies:list")

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        CompanyMembership.objects.update_or_create(
            user=self.request.user,
            company=self.object,
            defaults={"role": CompanyMembership.Role.ADMIN, "active": True},
        )
        self.request.session[ACTIVE_COMPANY_SESSION_KEY] = self.object.pk
        messages.success(self.request, "Société créée avec succès.")
        return response


class CompanyUpdateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = Company
    form_class = CompanyForm
    template_name = "companies/form.html"
    success_url = reverse_lazy("companies:list")
    required_company_permission = CompanyPermission.CHANGE_COMPANY
    company_lookup = "pk"

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.object.active:
            clear_active_company(self.request)
        messages.success(self.request, "Société modifiée avec succès.")
        return response


class CompanyDeleteView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    DeleteView,
):
    model = Company
    template_name = "companies/delete.html"
    success_url = reverse_lazy("companies:list")
    required_company_permission = CompanyPermission.CHANGE_COMPANY
    company_lookup = "pk"

    def form_valid(self, form):
        response = super().form_valid(form)
        clear_active_company(self.request)
        messages.success(self.request, "Société supprimée avec succès.")
        return response
