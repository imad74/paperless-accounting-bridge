from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from accounts.mixins import (
    ActiveCompanyQuerysetMixin,
    CompanyPermissionRequiredMixin,
)
from accounts.permissions import CompanyPermission, role_has_permission

from .forms import DocumentTypeForm
from .models import Document, DocumentType


class DocumentListView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    ListView,
):
    model = Document
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS


class DocumentTypeListView(CompanyPermissionRequiredMixin, ListView):
    model = DocumentType
    template_name = "documents/document_type_list.html"
    context_object_name = "document_types"
    paginate_by = 20
    required_company_permission = CompanyPermission.VIEW_DOCUMENT_TYPES

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")

        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(prefix__icontains=search)
            )
        if status == "active":
            queryset = queryset.filter(active=True)
        elif status == "inactive":
            queryset = queryset.filter(active=False)

        return queryset.order_by("name", "code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage_document_types"] = role_has_permission(
            self.active_company_membership.role,
            CompanyPermission.MANAGE_DOCUMENT_TYPES,
        )
        query_parameters = self.request.GET.copy()
        query_parameters.pop("page", None)
        context["pagination_query"] = query_parameters.urlencode()
        context["current_status"] = self.request.GET.get("status", "")
        return context


class DocumentTypeCreateView(CompanyPermissionRequiredMixin, CreateView):
    model = DocumentType
    form_class = DocumentTypeForm
    template_name = "documents/document_type_form.html"
    success_url = reverse_lazy("document_types:list")
    required_company_permission = CompanyPermission.MANAGE_DOCUMENT_TYPES
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Type documentaire créé avec succès.")
        return response


class DocumentTypeUpdateView(CompanyPermissionRequiredMixin, UpdateView):
    model = DocumentType
    form_class = DocumentTypeForm
    template_name = "documents/document_type_form.html"
    success_url = reverse_lazy("document_types:list")
    required_company_permission = CompanyPermission.MANAGE_DOCUMENT_TYPES
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Type documentaire modifié avec succès.")
        return response


class DocumentTypeToggleActiveView(CompanyPermissionRequiredMixin, View):
    required_company_permission = CompanyPermission.MANAGE_DOCUMENT_TYPES
    http_method_names = ("post", "options")

    def post(self, request, pk):
        document_type = get_object_or_404(DocumentType, pk=pk)
        document_type.active = not document_type.active
        document_type.save(update_fields=("active",))

        state = "activé" if document_type.active else "désactivé"
        messages.success(
            request,
            f"Le type documentaire {document_type.code} a été {state}.",
        )
        return redirect("document_types:list")
