from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import View

from accounts.mixins import ActiveCompanyRequiredMixin


class HomeView(ActiveCompanyRequiredMixin, View):
    """Render the landing page for the application."""

    def get(self, request):
        return render(
            request,
            "dashboard/home.html",
            {
                "title": "Paperless Accounting Bridge",
            },
        )


def health_check(request):
    """Simple health endpoint used by Docker and monitoring."""
    return JsonResponse({"status": "ok", "service": "paperless-accounting-bridge"})
