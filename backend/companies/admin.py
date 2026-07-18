from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "city",
        "country",
        "active",
        "created_at",
    )

    list_filter = (
        "active",
        "country",
    )

    search_fields = (
        "code",
        "name",
        "city",
        "email",
    )

    ordering = ("name",)