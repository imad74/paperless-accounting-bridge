from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, FormView, ListView, UpdateView

from accounts.mixins import ActiveCompanyQuerysetMixin, CompanyPermissionRequiredMixin
from accounts.permissions import CompanyPermission, role_has_permission
from documents.paperless_api import PaperlessApiError

from .ai_extraction import AiExtractionError
from .forms import (
    PaperlessInvoiceImportForm,
    PurchaseInvoiceForm,
    PurchaseInvoiceLineFormSet,
    SupplierForm,
)
from .models import InvoiceNature, PurchaseInvoice, Supplier
from .services import (
    PurchaseInvoiceImportService,
    rebuild_tax_summaries,
    queue_ai_analysis,
    refresh_supplier_identity,
)


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
        nature = self.request.GET.get("nature", "").strip()
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search)
                | Q(paperless_title__icontains=search)
                | Q(original_filename__icontains=search)
                | Q(supplier__name__icontains=search)
                | Q(supplier_name_raw__icontains=search)
                | Q(supplier_ice_raw__icontains=search)
            )
        if status in PurchaseInvoice.Status.values:
            queryset = queryset.filter(status=status)
        if nature in InvoiceNature.values:
            queryset = queryset.filter(nature=nature)
        return queryset.order_by("-invoice_date", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = PurchaseInvoice.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        context["natures"] = InvoiceNature.choices
        context["current_nature"] = self.request.GET.get("nature", "")
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
        except (PaperlessApiError, AiExtractionError) as error:
            form.add_error("paperless_document_id", str(error))
            return self.form_invalid(form)

        if created:
            messages.success(
                self.request,
                "Facture importée. Vérifiez les champs et chaque ligne avant validation.",
            )
            if invoice.nature != InvoiceNature.GOODS:
                messages.warning(
                    self.request,
                    f"Nature détectée : {invoice.get_nature_display()}. "
                    "Seuls les achats de marchandises alimentent le stock.",
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
        context["ai_extraction_available"] = settings.PURCHASES_AI_ENABLED
        context["ai_job"] = getattr(self.object, "ai_analysis_job", None)
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


class PurchaseInvoiceRefreshSupplierView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = PurchaseInvoice
    fields = ()
    http_method_names = ("post", "options")
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def post(self, request, *args, **kwargs):
        invoice = self.get_object()
        changed, ambiguous_ice = refresh_supplier_identity(invoice)
        if ambiguous_ice:
            messages.warning(
                request,
                "Plusieurs ICE ont été trouvés. Sélectionnez manuellement l’ICE du fournisseur.",
            )
        elif changed:
            messages.success(
                request,
                "Le nom et l’ICE du fournisseur ont été relus depuis le texte OCR.",
            )
        else:
            messages.info(
                request,
                "Aucune nouvelle identité fournisseur fiable n’a été reconnue. Complétez les champs manuellement.",
            )
        return redirect("purchases:update", pk=invoice.pk)


class PurchaseInvoiceAnalyzeAiView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = PurchaseInvoice
    fields = ()
    http_method_names = ("post", "options")
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def post(self, request, *args, **kwargs):
        invoice = self.get_object()
        try:
            job = queue_ai_analysis(invoice, requested_by=request.user)
        except AiExtractionError as error:
            messages.error(request, f"Mise en file impossible : {error}")
        else:
            messages.success(
                request,
                f"Analyse locale mise en attente avec {job.model_name}. "
                "Vous pouvez quitter cette page ; le traitement continue en arrière-plan.",
            )
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
        return reverse_lazy("purchases:supplier_list")


SUPPLIER_SORTS = {
    "documents": ("-paperless_document_count", "name"),
    "nom": ("name",),
    "total": (F("detected_total_ttc").desc(nulls_last=True), "name"),
    "recent": (F("last_document_date").desc(nulls_last=True), "name"),
}


def filtered_suppliers(request, company):
    """Fournisseurs de la société filtrés par recherche, nature effective et activité."""
    queryset = Supplier.objects.filter(company=company)
    search = request.GET.get("q", "").strip()
    nature = request.GET.get("nature", "").strip()
    activity = request.GET.get("activite", "").strip()
    validated = request.GET.get("validee", "").strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(ice__icontains=search) | Q(activity__icontains=search)
        )
    if nature in InvoiceNature.values:
        queryset = queryset.filter(
            Q(default_nature=nature) | (Q(default_nature="") & Q(detected_nature=nature))
        )
    if activity == "-":
        queryset = queryset.filter(activity="")
    elif activity:
        queryset = queryset.filter(activity__iexact=activity)
    if validated == "oui":
        queryset = queryset.exclude(default_nature="")
    elif validated == "auto":
        queryset = queryset.exclude(default_nature="").filter(
            nature_validation=Supplier.NatureValidation.AUTO
        )
    elif validated == "manuelle":
        queryset = queryset.exclude(default_nature="").filter(
            nature_validation=Supplier.NatureValidation.MANUAL
        )
    elif validated == "non":
        queryset = queryset.filter(default_nature="")
    sort = request.GET.get("tri", "documents")
    return queryset.order_by(*SUPPLIER_SORTS.get(sort, SUPPLIER_SORTS["documents"]))


class SupplierListView(CompanyPermissionRequiredMixin, ListView):
    model = Supplier
    template_name = "purchases/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 50
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS

    def get_queryset(self):
        return filtered_suppliers(self.request, self.active_company)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_suppliers = Supplier.objects.filter(company=self.active_company)
        context["natures"] = InvoiceNature.choices
        context["activities"] = (
            all_suppliers.exclude(activity="")
            .values_list("activity", flat=True)
            .distinct()
            .order_by("activity")
        )
        context["summary"] = {
            "total": all_suppliers.count(),
            "validated": all_suppliers.exclude(default_nature="").count(),
            "auto_validated": all_suppliers.exclude(default_nature="")
            .filter(nature_validation=Supplier.NatureValidation.AUTO)
            .count(),
            "without_activity": all_suppliers.filter(activity="").count(),
        }
        context["query_string"] = self.request.GET.urlencode()
        context["can_change"] = role_has_permission(
            self.active_company_membership.role,
            CompanyPermission.CHANGE_DOCUMENTS,
        )
        return context


class SupplierUpdateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = Supplier
    form_class = SupplierForm
    template_name = "purchases/supplier_form.html"
    required_company_permission = CompanyPermission.CHANGE_DOCUMENTS

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.active_company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activities"] = (
            Supplier.objects.filter(company=self.active_company)
            .exclude(activity="")
            .values_list("activity", flat=True)
            .distinct()
            .order_by("activity")
        )
        context["recent_invoices"] = self.object.invoices.order_by("-invoice_date")[:10]
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Fournisseur mis à jour.")
        return response

    def get_success_url(self):
        return reverse("purchases:supplier_list")


class SupplierExportView(CompanyPermissionRequiredMixin, ListView):
    """Export Excel de la liste des fournisseurs, avec les mêmes filtres que l'écran."""

    model = Supplier
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS

    def get(self, request, *args, **kwargs):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Fournisseurs"
        headers = (
            "Nom", "ICE", "IF", "RC", "Activité", "Nature retenue", "Nature validée",
            "Nature détectée", "Validation", "Répartition détectée", "Documents Paperless",
            "Total TTC détecté (MAD)", "Première facture", "Dernière facture", "Ville", "Actif",
        )
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        labels = dict(InvoiceNature.choices)
        for supplier in filtered_suppliers(request, self.active_company):
            sheet.append((
                supplier.name,
                supplier.ice,
                supplier.if_number,
                supplier.rc,
                supplier.activity,
                labels.get(supplier.effective_nature, ""),
                labels.get(supplier.default_nature, ""),
                labels.get(supplier.detected_nature, ""),
                supplier.get_nature_validation_display() if supplier.default_nature else "à valider",
                supplier.detected_nature_details,
                supplier.paperless_document_count,
                float(supplier.detected_total_ttc) if supplier.detected_total_ttc is not None else None,
                supplier.first_document_date,
                supplier.last_document_date,
                supplier.city,
                "oui" if supplier.active else "non",
            ))
        widths = (40, 18, 12, 12, 22, 26, 26, 26, 14, 45, 12, 18, 14, 14, 16, 8)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for row in sheet.iter_rows(min_row=2, min_col=12, max_col=12):
            for cell in row:
                cell.number_format = "#,##0.00"
        for row in sheet.iter_rows(min_row=2, min_col=13, max_col=14):
            for cell in row:
                cell.number_format = "DD/MM/YYYY"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"fournisseurs-{self.active_company.code.lower()}-{timezone.localdate():%Y%m%d}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        workbook.save(response)
        return response
