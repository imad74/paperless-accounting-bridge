from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin

from accounts.mixins import (
    ActiveCompanyQuerysetMixin,
    CompanyPermissionRequiredMixin,
)
from accounts.permissions import CompanyPermission, role_has_permission

from .forms import DocumentFilterForm, DocumentForm, DocumentTypeForm
from .models import Document, DocumentType
from .services import NumberingService


class DocumentListView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    ListView,
):
    model = Document
    template_name = "documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 20
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS

    def get_queryset(self):
        queryset = super().get_queryset().select_related("document_type")
        self.filter_form = DocumentFilterForm(self.request.GET or None)

        if self.filter_form.is_valid():
            search = self.filter_form.cleaned_data["q"]
            document_type = self.filter_form.cleaned_data["document_type"]
            status = self.filter_form.cleaned_data["status"]
            period = self.filter_form.cleaned_data["period"]

            if search:
                queryset = queryset.filter(
                    Q(number__icontains=search)
                    | Q(title__icontains=search)
                    | Q(original_filename__icontains=search)
                )
            if document_type:
                queryset = queryset.filter(document_type=document_type)
            if status:
                queryset = queryset.filter(status=status)
            if period:
                year, month = (int(value) for value in period.split("-"))
                queryset = queryset.filter(
                    document_date__year=year,
                    document_date__month=month,
                )

        return queryset.order_by("-document_date", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.active_company_membership.role
        context["filter_form"] = self.filter_form
        context["can_change_documents"] = role_has_permission(
            role,
            CompanyPermission.CHANGE_DOCUMENTS,
        )
        context["can_archive_documents"] = role_has_permission(
            role,
            CompanyPermission.ARCHIVE_DOCUMENTS,
        )
        query_parameters = self.request.GET.copy()
        query_parameters.pop("page", None)
        context["pagination_query"] = query_parameters.urlencode()
        return context


class DocumentCreateView(CompanyPermissionRequiredMixin, CreateView):
    model = Document
    form_class = DocumentForm
    template_name = "documents/document_form.html"
    success_url = reverse_lazy("documents:list")
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        form.instance.company = self.active_company
        form.instance.created_by = self.request.user
        form.instance.status = Document.Status.NEW

        try:
            with transaction.atomic():
                form.instance.number = NumberingService.generate(
                    company=self.active_company,
                    document_type_code=form.cleaned_data["document_type"].code,
                    generation_date=form.cleaned_data["document_date"],
                )
                response = super().form_valid(form)
        except ValueError as error:
            form.add_error("document_type", str(error))
            return self.form_invalid(form)

        messages.success(self.request, "Document créé avec succès.")
        return response


class DocumentUpdateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = Document
    form_class = DocumentForm
    template_name = "documents/document_form.html"
    success_url = reverse_lazy("documents:list")
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Document modifié avec succès.")
        return response


class DocumentArchiveView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    SingleObjectMixin,
    View,
):
    model = Document
    required_company_permission = CompanyPermission.ARCHIVE_DOCUMENTS
    http_method_names = ("post", "options")

    def post(self, request, *args, **kwargs):
        document = self.get_object()
        if document.status != Document.Status.ARCHIVED:
            document.status = Document.Status.ARCHIVED
            document.save(update_fields=("status", "updated_at"))
            messages.success(request, "Document archivé avec succès.")
        else:
            messages.info(request, "Ce document est déjà archivé.")
        return redirect("documents:list")


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
