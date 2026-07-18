from django.contrib import admin

from .models import ImportJob


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