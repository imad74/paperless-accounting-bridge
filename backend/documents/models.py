from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company


class DocumentType(models.Model):
    """Defines a category of documents and its numbering prefix."""

    code = models.CharField(max_length=10, unique=True, verbose_name="code")
    name = models.CharField(max_length=255, verbose_name="name")
    prefix = models.CharField(max_length=20, unique=True, verbose_name="prefix")
    description = models.TextField(blank=True, verbose_name="description")
    yearly_reset = models.BooleanField(default=True, verbose_name="yearly reset")
    active = models.BooleanField(default=True, verbose_name="active")

    class Meta:
        verbose_name = "document type"
        verbose_name_plural = "document types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def normalize_identifier(value: str) -> str:
        return (value or "").strip().upper()

    def clean(self):
        super().clean()
        errors = {}

        for field_name, label in (("code", "code"), ("prefix", "préfixe")):
            normalized_value = self.normalize_identifier(
                getattr(self, field_name, "")
            )
            setattr(self, field_name, normalized_value)

            if not normalized_value:
                errors[field_name] = f"Le {label} est obligatoire."
                continue

            duplicate_exists = type(self).objects.filter(
                **{f"{field_name}__iexact": normalized_value}
            ).exclude(pk=self.pk).exists()
            if duplicate_exists:
                errors[field_name] = (
                    f"Un type documentaire avec ce {label} existe déjà."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = self.normalize_identifier(self.code)
        self.prefix = self.normalize_identifier(self.prefix)
        return super().save(*args, **kwargs)


class Document(models.Model):
    """Represents a document imported into the system."""

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        IMPORTED = "IMPORTED", "Imported"
        FAILED = "FAILED", "Failed"
        ARCHIVED = "ARCHIVED", "Archived"

    number = models.CharField(max_length=255, unique=True, verbose_name="number")
    title = models.CharField(max_length=255, verbose_name="title")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="documents", verbose_name="company")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="documents", verbose_name="document type")
    paperless_id = models.IntegerField(null=True, blank=True, verbose_name="paperless id")
    original_filename = models.CharField(max_length=255, verbose_name="original filename")
    stored_filename = models.CharField(max_length=255, verbose_name="stored filename")
    document_date = models.DateField(verbose_name="document date")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="amount")
    currency = models.CharField(max_length=3, default="MAD", verbose_name="currency")
    notes = models.TextField(blank=True, verbose_name="notes")
    sha256 = models.CharField(max_length=64, unique=True, blank=True, null=True, verbose_name="sha256")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_documents", verbose_name="created by")
    imported_at = models.DateTimeField(auto_now_add=True, verbose_name="imported at")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="created at")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="updated at")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, verbose_name="status")

    class Meta:
        verbose_name = "document"
        verbose_name_plural = "documents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["document_type", "status"]),
            models.Index(fields=["document_date"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} - {self.title}"


class DocumentCounter(models.Model):
    """Tracks the current counter used to generate document numbers."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="document_counters",
        verbose_name="company",
    )
    document_type = models.ForeignKey(DocumentType, on_delete=models.CASCADE, related_name="counters", verbose_name="document type")
    year = models.PositiveIntegerField(verbose_name="year")
    current_number = models.PositiveIntegerField(default=0, verbose_name="current number")

    class Meta:
        verbose_name = "document counter"
        verbose_name_plural = "document counters"
        ordering = ["company__code", "document_type__code", "year"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "document_type", "year"],
                name="unique_document_counter_scope",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.document_type_id:
            return

        if self.document_type.yearly_reset and self.year == 0:
            raise ValidationError(
                {"year": "Un compteur annuel doit utiliser une année réelle."}
            )
        if not self.document_type.yearly_reset and self.year != 0:
            raise ValidationError(
                {"year": "Un compteur continu doit utiliser l’année technique 0."}
            )

    def __str__(self) -> str:
        period = self.year if self.year else "continu"
        return f"{self.company.code}-{self.document_type.prefix}-{period}"
