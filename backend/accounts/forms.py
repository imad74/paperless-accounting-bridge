from django import forms
from django.contrib.auth import get_user_model

from .models import CompanyMembership
from .services import available_company_memberships


class CompanyMembershipChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, membership: CompanyMembership) -> str:
        return (
            f"{membership.company.name} — "
            f"{membership.get_role_display()}"
        )


class CompanySelectionForm(forms.Form):
    membership = CompanyMembershipChoiceField(
        label="Société",
        queryset=CompanyMembership.objects.none(),
        empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    next = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = available_company_memberships(user)


class ExistingUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user) -> str:
        full_name = user.get_full_name().strip()
        identity = f"{full_name} ({user.get_username()})" if full_name else user.get_username()
        return f"{identity} — {user.email}" if user.email else identity


class CompanyMembershipCreateForm(forms.ModelForm):
    user = ExistingUserChoiceField(
        label="Utilisateur",
        queryset=get_user_model().objects.none(),
        empty_label="Sélectionner un utilisateur",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = CompanyMembership
        fields = ("user", "role", "active")
        labels = {
            "role": "Rôle",
            "active": "Appartenance active",
        }
        widgets = {
            "role": forms.Select(attrs={"class": "form-select"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.instance.company = company
        self.fields["user"].queryset = (
            get_user_model().objects.filter(is_active=True)
            .exclude(company_memberships__company=company)
            .order_by("username")
        )


class CompanyMembershipUpdateForm(forms.ModelForm):
    class Meta:
        model = CompanyMembership
        fields = ("role", "active")
        labels = {
            "role": "Rôle",
            "active": "Appartenance active",
        }
        widgets = {
            "role": forms.Select(attrs={"class": "form-select"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
