from django.contrib import admin

from .models import PurchaseInvoice, PurchaseInvoiceLine, PurchaseInvoiceTaxSummary, Supplier
from .services import rebuild_tax_summaries


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "ice", "if_number", "active")
    list_filter = ("company", "active")
    search_fields = ("name", "ice", "if_number", "rc")


class PurchaseInvoiceLineInline(admin.TabularInline):
    model = PurchaseInvoiceLine
    extra = 0


class PurchaseInvoiceTaxSummaryInline(admin.TabularInline):
    model = PurchaseInvoiceTaxSummary
    extra = 0
    can_delete = False
    readonly_fields = ("tax_rate", "taxable_amount", "tax_amount")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "supplier",
        "company",
        "invoice_date",
        "total_ttc",
        "currency",
        "status",
        "paperless_document_id",
    )
    list_filter = ("company", "status", "currency", "invoice_date")
    search_fields = (
        "invoice_number",
        "supplier__name",
        "paperless_title",
        "original_filename",
    )
    inlines = (PurchaseInvoiceLineInline, PurchaseInvoiceTaxSummaryInline)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is PurchaseInvoiceLine:
            rebuild_tax_summaries(form.instance)
