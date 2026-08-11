from django.contrib import admin

from .models import ImportJob, PaperlessOutbox


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):

    list_display = (
        "filename",
        "source",
        "success",
        "processed_documents",
        "failed_documents",
        "started_at",
        "finished_at",
    )

    list_filter = (
        "success",
        "source",
    )

    search_fields = (
        "filename",
        "source",
        "message",
    )

    readonly_fields = (
        "started_at",
        "finished_at",
        "duration",
    )

    ordering = (
        "-started_at",
    )


@admin.register(PaperlessOutbox)
class PaperlessOutboxAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "document",
        "attempt_count",
        "delivered_at",
        "created_at",
    )
    list_filter = ("delivered_at",)
    search_fields = ("filename", "document__number")
    readonly_fields = (
        "document",
        "filename",
        "attempt_count",
        "last_error",
        "delivered_at",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
