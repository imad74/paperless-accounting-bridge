from django import forms

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
