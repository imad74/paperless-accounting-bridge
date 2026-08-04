from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView

from .forms import CompanySelectionForm
from .services import set_active_company


class CompanySelectionView(LoginRequiredMixin, FormView):
    form_class = CompanySelectionForm
    template_name = "accounts/company_select.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial["next"] = self.request.GET.get("next", "")
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_available_companies"] = context[
            "form"
        ].fields["membership"].queryset.exists()
        return context

    def form_valid(self, form):
        membership = form.cleaned_data["membership"]
        set_active_company(self.request, membership.company_id)
        messages.success(
            self.request,
            f"La société active est maintenant {membership.company.name}.",
        )
        return redirect(self.get_success_url(form.cleaned_data.get("next")))

    def get_success_url(self, next_url=""):
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("home")
