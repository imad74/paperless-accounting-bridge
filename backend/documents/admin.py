from django.contrib import admin

from .models import (
    Document,
    DocumentCounter,
    DocumentType,
)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):

    list_display = (
        "code",
        "name",
        "prefix",
        "yearly_reset",
        "active",
    )

    list_filter = (
        "active",
        "yearly_reset",
    )

    search_fields = (
        "code",
        "name",
    )

    ordering = ("code",)


@admin.register(DocumentCounter)
class DocumentCounterAdmin(admin.ModelAdmin):

    list_display = (
        "company",
        "document_type",
        "year",
        "current_number",
    )

    list_filter = (
        "company",
        "year",
    )

    autocomplete_fields = (
        "company",
        "document_type",
    )

    ordering = (
        "company",
        "-year",
        "document_type",
    )

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):

    list_display = (
        "number",
        "title",
        "company",
        "document_type",
        "document_date",
        "amount",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "document_type",
        "company",
        "document_date",
    )

    search_fields = (
        "number",
        "title",
        "original_filename",
    )

    autocomplete_fields = (
        "company",
        "document_type",
    )

    ordering = (
        "-created_at",
    )
