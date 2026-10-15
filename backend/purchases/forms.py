from decimal import Decimal

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.db.models import Q

from .models import PurchaseInvoice, PurchaseInvoiceLine, Supplier


class PaperlessInvoiceImportForm(forms.Form):
    paperless_document_id = forms.IntegerField(
        min_value=1,
        label="Identifiant du document Paperless",
        help_text="L’identifiant apparaît dans l’adresse de la fiche Paperless.",
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Ex. 7890"}
        ),
    )


class PurchaseInvoiceForm(forms.ModelForm):
    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Supplier.objects.none()
        if company is not None:
            suppliers = Supplier.objects.filter(company=company, active=True)
            if self.instance.pk and self.instance.supplier_id:
                suppliers = Supplier.objects.filter(company=company).filter(
                    Q(active=True) | Q(pk=self.instance.supplier_id)
                )
        self.fields["supplier"].queryset = suppliers.order_by("name")
        self.fields["supplier"].empty_label = "Sélectionner un fournisseur"

    class Meta:
        model = PurchaseInvoice
        fields = (
            "supplier",
            "supplier_name_raw",
            "invoice_number",
            "invoice_date",
            "due_date",
            "currency",
            "subtotal_ht",
            "discount_amount",
            "net_ht",
            "tax_amount",
            "total_ttc",
            "extraction_notes",
        )
        labels = {
            "supplier_name_raw": "Nom fournisseur lu par l’OCR",
            "extraction_notes": "Notes et anomalies",
        }
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "supplier_name_raw": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_number": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "currency": forms.TextInput(attrs={"class": "form-control", "maxlength": 3}),
            "subtotal_ht": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "discount_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "net_ht": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "tax_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "total_ttc": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "extraction_notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean_currency(self):
        return self.cleaned_data["currency"].strip().upper()


class PurchaseInvoiceLineForm(forms.ModelForm):
    class Meta:
        model = PurchaseInvoiceLine
        fields = (
            "position",
            "reference",
            "description",
            "quantity",
            "unit",
            "unit_price_ht",
            "discount_percent",
            "tax_rate",
            "total_ht",
            "tax_amount",
            "total_ttc",
            "verified",
        )
        widgets = {
            "position": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 1}),
            "reference": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "description": forms.Textarea(attrs={"class": "form-control form-control-sm", "rows": 2}),
            "quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.0001"}),
            "unit": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "unit_price_ht": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.0001"}),
            "discount_percent": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "tax_rate": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "total_ht": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "tax_amount": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "total_ttc": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "verified": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BasePurchaseInvoiceLineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        positions = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            if not form.cleaned_data.get("description"):
                continue
            position = form.cleaned_data.get("position")
            if position in positions:
                raise forms.ValidationError("Chaque ligne doit avoir une position unique.")
            positions.add(position)

            total_ht = form.cleaned_data.get("total_ht") or Decimal("0")
            tax_amount = form.cleaned_data.get("tax_amount") or Decimal("0")
            total_ttc = form.cleaned_data.get("total_ttc") or Decimal("0")
            if abs(total_ht + tax_amount - total_ttc) > Decimal("0.02"):
                raise forms.ValidationError(
                    f"La ligne {position} ne respecte pas HT + TVA = TTC."
                )


PurchaseInvoiceLineFormSet = inlineformset_factory(
    PurchaseInvoice,
    PurchaseInvoiceLine,
    form=PurchaseInvoiceLineForm,
    formset=BasePurchaseInvoiceLineFormSet,
    extra=1,
    can_delete=True,
)


class SupplierForm(forms.ModelForm):
    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

    class Meta:
        model = Supplier
        fields = ("name", "ice", "if_number", "rc", "address", "city", "country", "active")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "ice": forms.TextInput(attrs={"class": "form-control"}),
            "if_number": forms.TextInput(attrs={"class": "form-control"}),
            "rc": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if self.company is None:
            return name

        duplicates = Supplier.objects.filter(
            company=self.company,
            normalized_name=Supplier.normalize_name(name),
        )
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(
                "Un fournisseur portant ce nom existe déjà pour la société active."
            )
        return name
