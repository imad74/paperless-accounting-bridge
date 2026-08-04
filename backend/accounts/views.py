from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, DeleteView, FormView, ListView, UpdateView

from .forms import (
    CompanyMembershipCreateForm,
    CompanyMembershipUpdateForm,
    CompanySelectionForm,
)
from .mixins import ActiveCompanyQuerysetMixin, CompanyPermissionRequiredMixin
from .models import CompanyMembership
from .permissions import CompanyPermission
from .services import (
    LastActiveAdministratorError,
    delete_company_membership,
    set_active_company,
    update_company_membership,
)


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


class CompanyMembershipListView(CompanyPermissionRequiredMixin, ListView):
    model = CompanyMembership
    template_name = "accounts/membership_list.html"
    context_object_name = "memberships"
    paginate_by = 20
    required_company_permission = CompanyPermission.MANAGE_MEMBERS

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(company_id=self.active_company.pk)
            .select_related("user")
            .order_by("user__username")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_admin_count"] = CompanyMembership.objects.filter(
            company_id=self.active_company.pk,
            role=CompanyMembership.Role.ADMIN,
            active=True,
        ).count()
        return context


class CompanyMembershipCreateView(
    CompanyPermissionRequiredMixin,
    CreateView,
):
    model = CompanyMembership
    form_class = CompanyMembershipCreateForm
    template_name = "accounts/membership_form.html"
    success_url = reverse_lazy("accounts:membership_list")
    required_company_permission = CompanyPermission.MANAGE_MEMBERS
    http_method_names = ("get", "post", "head", "options")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.active_company
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except IntegrityError:
            form.add_error(
                "user",
                "Cet utilisateur appartient déjà à cette société.",
            )
            return self.form_invalid(form)

        messages.success(self.request, "Membre ajouté avec succès.")
        return response


class CompanyMembershipUpdateView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    UpdateView,
):
    model = CompanyMembership
    form_class = CompanyMembershipUpdateForm
    template_name = "accounts/membership_form.html"
    success_url = reverse_lazy("accounts:membership_list")
    required_company_permission = CompanyPermission.MANAGE_MEMBERS
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        try:
            self.object = update_company_membership(
                membership_id=self.object.pk,
                company_id=self.active_company.pk,
                role=form.cleaned_data["role"],
                active=form.cleaned_data["active"],
            )
        except LastActiveAdministratorError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Appartenance modifiée avec succès.")
        return HttpResponseRedirect(self.get_success_url())


class CompanyMembershipDeleteView(
    CompanyPermissionRequiredMixin,
    ActiveCompanyQuerysetMixin,
    DeleteView,
):
    model = CompanyMembership
    template_name = "accounts/membership_delete.html"
    success_url = reverse_lazy("accounts:membership_list")
    required_company_permission = CompanyPermission.MANAGE_MEMBERS
    http_method_names = ("get", "post", "head", "options")

    def form_valid(self, form):
        member_name = str(self.object.user)
        try:
            delete_company_membership(
                membership_id=self.object.pk,
                company_id=self.active_company.pk,
            )
        except LastActiveAdministratorError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"L’appartenance de {member_name} a été supprimée.",
        )
        return HttpResponseRedirect(self.get_success_url())
