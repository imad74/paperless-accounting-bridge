from django import forms
from django.db.models import Q

from .models import Document, DocumentType


class DocumentForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        document_types = DocumentType.objects.filter(active=True)
        if self.instance.pk and self.instance.document_type_id:
            document_types = DocumentType.objects.filter(
                Q(active=True) | Q(pk=self.instance.document_type_id)
            )
        self.fields["document_type"].queryset = document_types.order_by("name")

    class Meta:
        model = Document
        fields = [
            "title",
            "company",
            "document_type",
            "document_date",
            "amount",
            "currency",
            "status",
            "notes",
        ]


class DocumentTypeForm(forms.ModelForm):
    class Meta:
        model = DocumentType
        fields = (
            "code",
            "name",
            "prefix",
            "description",
            "yearly_reset",
            "active",
        )
        labels = {
            "code": "Code",
            "name": "Nom",
            "prefix": "Préfixe",
            "description": "Description",
            "yearly_reset": "Réinitialisation annuelle",
            "active": "Type actif",
        }
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "prefix": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
            "yearly_reset": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }

    def clean_code(self):
        return DocumentType.normalize_identifier(self.cleaned_data["code"])

    def clean_prefix(self):
        return DocumentType.normalize_identifier(self.cleaned_data["prefix"])
