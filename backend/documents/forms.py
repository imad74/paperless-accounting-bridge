from django import forms
from .models import Document, DocumentType

class DocumentForm(forms.ModelForm):
    class Meta:
        model=Document
        fields=["title","company","document_type","document_date","amount","currency","status","notes"]

class DocumentTypeForm(forms.ModelForm):
    class Meta:
        model=DocumentType
        fields="__all__"
