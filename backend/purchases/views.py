from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, FormView, ListView, UpdateView

from accounts.mixins import ActiveCompanyQuerysetMixin, CompanyPermissionRequiredMixin
from accounts.permissions import CompanyPermission, role_has_permission
from documents.paperless_api import PaperlessApiError

from .forms import (
    PaperlessInvoiceImportForm,
    PurchaseInvoiceForm,
    PurchaseInvoiceLineFormSet,
    SupplierForm,
)
from .models import PurchaseInvoice, Supplier
from .services import PurchaseInvoiceImportService, rebuild_tax_summaries


class PurchaseInvoiceListView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    ListView,
):
    model = PurchaseInvoice
    template_name = "purchases/purchase_invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("supplier")
            .annotate(line_count=Count("lines"))
        )
        search = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search)
                | Q(paperless_title__icontains=search)
                | Q(original_filename__icontains=search)
                | Q(supplier__name__icontains=search)
                | Q(supplier_name_raw__icontains=search)
            )
        if status in PurchaseInvoice.Status.values:
            queryset = queryset.filter(status=status)
        return queryset.order_by("-invoice_date", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = PurchaseInvoice.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        context["can_change"] = role_has_permission(
            self.active_company_membership.role,
            CompanyPermission.CHANGE_DOCUMENTS,
        )
        return context


class PurchaseInvoiceImportView(CompanyPermissionRequiredMixin, FormView):
    template_name = "purchases/purchase_invoice_import.html"
    form_class = PaperlessInvoiceImportForm
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def get_initial(self):
        initial = super().get_initial()
        paperless_id = self.request.GET.get("paperless_id", "").strip()
        if paperless_id.isdigit():
            initial["paperless_document_id"] = paperless_id
        return initial

    def form_valid(self, form):
        try:
            invoice, created = PurchaseInvoiceImportService().import_document(
                company=self.active_company,
                paperless_document_id=form.cleaned_data["paperless_document_id"],
            )
        except PaperlessApiError as error:
            form.add_error("paperless_document_id", str(error))
            return self.form_invalid(form)

        if created:
            messages.success(
                self.request,
                "Facture importée. Vérifiez les champs et chaque ligne avant validation.",
            )
        else:
            messages.info(self.request, "Cette facture Paperless est déjà importée.")
        return redirect("purchases:update", pk=invoice.pk)


class PurchaseInvoiceUpdateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = PurchaseInvoice
    form_class = PurchaseInvoiceForm
    template_name = "purchases/purchase_invoice_form.html"
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.active_company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            context["line_formset"] = PurchaseInvoiceLineFormSet(
                self.request.POST,
                instance=self.object,
                prefix="lines",
            )
        else:
            context["line_formset"] = PurchaseInvoiceLineFormSet(
                instance=self.object,
                prefix="lines",
            )
        context["can_validate"] = role_has_permission(
            self.active_company_membership.role,
            CompanyPermission.ARCHIVE_DOCUMENTS,
        )
        context["paperless_url"] = settings.PAPERLESS_API_URL.rstrip("/")
        return context

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        formset = context["line_formset"]
        if not formset.is_valid():
            return self.form_invalid(form)
        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.status = PurchaseInvoice.Status.TO_REVIEW
            self.object.validated_by = None
            self.object.validated_at = None
            self.object.save()
            formset.instance = self.object
            formset.save()
            rebuild_tax_summaries(self.object)
        messages.success(self.request, "La facture et ses lignes ont été enregistrées.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("purchases:update", args=(self.object.pk,))


class PurchaseInvoiceValidateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = PurchaseInvoice
    fields = ()
    http_method_names = ("post", "options")
    required_company_permission = CompanyPermission.ARCHIVE_DOCUMENTS

    def post(self, request, *args, **kwargs):
        invoice = self.get_object()
        errors = []
        if not invoice.supplier_id:
            errors.append("sélectionner un fournisseur validé")
        if not invoice.invoice_number:
            errors.append("renseigner le numéro de facture")
        if not invoice.invoice_date:
            errors.append("renseigner la date de facture")
        if not invoice.lines.exists():
            errors.append("ajouter au moins une ligne")
        if not invoice.lines.filter(verified=False).exists() and not invoice.is_balanced:
            errors.append("équilibrer les lignes avec les totaux HT, TVA et TTC")
        elif invoice.lines.filter(verified=False).exists():
            errors.append("marquer toutes les lignes comme vérifiées")

        if errors:
            messages.error(request, "Validation impossible : " + "; ".join(errors) + ".")
        else:
            invoice.status = PurchaseInvoice.Status.VALIDATED
            invoice.validated_by = request.user
            invoice.validated_at = timezone.now()
            invoice.save(update_fields=("status", "validated_by", "validated_at", "updated_at"))
            messages.success(request, "La facture d’achat a été validée.")
        return redirect("purchases:update", pk=invoice.pk)


class SupplierCreateView(CompanyPermissionRequiredMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = "purchases/supplier_form.html"
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.active_company
        return kwargs

    def form_valid(self, form):
        form.instance.company = self.active_company
        response = super().form_valid(form)
        messages.success(self.request, "Fournisseur créé avec succès.")
        return response

    def get_success_url(self):
        return reverse_lazy("purchases:list")
