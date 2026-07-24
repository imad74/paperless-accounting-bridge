from django.contrib import admin

from .models import CompanyMembership


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "company",
        "role",
        "active",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "active",
        "role",
        "company",
    )
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "company__code",
        "company__name",
    )
    autocomplete_fields = (
        "user",
        "company",
    )
    list_select_related = (
        "user",
        "company",
    )
    ordering = (
        "company__name",
        "user__username",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
