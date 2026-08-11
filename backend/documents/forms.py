from pathlib import Path

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Document, DocumentType


class DocumentForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.pdf_file:
            self.fields.pop("pdf_file", None)
        elif not self.instance.pk:
            self.fields["pdf_file"].required = True
        document_types = DocumentType.objects.filter(active=True)
        if self.instance.pk and self.instance.document_type_id:
            document_types = DocumentType.objects.filter(
                Q(active=True) | Q(pk=self.instance.document_type_id)
            )
        self.fields["document_type"].queryset = document_types.order_by("name")
        self.fields["document_type"].empty_label = "Sélectionner un type"

    class Meta:
        model = Document
        fields = [
            "pdf_file",
            "title",
            "document_type",
            "document_date",
            "amount",
            "currency",
            "notes",
        ]
        labels = {
            "pdf_file": "Document PDF scanné",
            "title": "Titre",
            "document_type": "Type documentaire",
            "document_date": "Date du document",
            "amount": "Montant",
            "currency": "Devise",
            "notes": "Notes",
        }
        widgets = {
            "pdf_file": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "application/pdf,.pdf",
                }
            ),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "document_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "currency": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 3}
            ),
            "notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
        }

    def clean_currency(self):
        return self.cleaned_data["currency"].strip().upper()

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get("pdf_file")
        if pdf_file is None:
            return pdf_file

        if Path(pdf_file.name).suffix.lower() != ".pdf":
            raise ValidationError("Sélectionnez un fichier au format PDF.")
        if pdf_file.size > settings.DOCUMENT_PDF_MAX_BYTES:
            max_size_mb = settings.DOCUMENT_PDF_MAX_BYTES // (1024 * 1024)
            raise ValidationError(
                f"Le fichier PDF ne doit pas dépasser {max_size_mb} Mo."
            )

        current_position = pdf_file.tell()
        pdf_file.seek(0)
        header = pdf_file.read(1024)
        pdf_file.seek(current_position)
        if b"%PDF-" not in header:
            raise ValidationError(
                "Le fichier transmis ne contient pas un PDF valide."
            )
        return pdf_file


class DocumentFilterForm(forms.Form):
    STATUS_CHOICES = (
        ("", "Tous les statuts"),
        (Document.Status.NEW, "Nouveau"),
        (Document.Status.IMPORTED, "Importé"),
        (Document.Status.FAILED, "En erreur"),
        (Document.Status.ARCHIVED, "Archivé"),
    )

    q = forms.CharField(
        required=False,
        label="Recherche",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "type": "search",
                "placeholder": "Numéro, titre ou fichier d’origine",
            }
        ),
    )
    document_type = forms.ModelChoiceField(
        queryset=DocumentType.objects.none(),
        required=False,
        label="Type documentaire",
        empty_label="Tous les types",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        label="Statut",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    period = forms.RegexField(
        regex=r"^\d{4}-(0[1-9]|1[0-2])$",
        required=False,
        label="Période",
        error_messages={"invalid": "Saisissez une période valide."},
        widget=forms.TextInput(
            attrs={"class": "form-control", "type": "month"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_type"].queryset = DocumentType.objects.order_by(
            "name", "code"
        )


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
