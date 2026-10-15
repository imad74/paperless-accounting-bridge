from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, Sum

from companies.models import Company
from documents.models import Document


ZERO = Decimal("0")
BALANCE_TOLERANCE = Decimal("0.02")


class Supplier(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="suppliers",
        verbose_name="société",
    )
    name = models.CharField(max_length=255, verbose_name="raison sociale")
    normalized_name = models.CharField(max_length=255, editable=False)
    ice = models.CharField(max_length=30, blank=True, db_index=True)
    if_number = models.CharField(max_length=30, blank=True, verbose_name="IF")
    rc = models.CharField(max_length=30, blank=True, verbose_name="RC")
    address = models.TextField(blank=True, verbose_name="adresse")
    city = models.CharField(max_length=100, blank=True, verbose_name="ville")
    country = models.CharField(
        max_length=100,
        default="Maroc",
        verbose_name="pays",
    )
    active = models.BooleanField(default=True, verbose_name="actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "fournisseur"
        verbose_name_plural = "fournisseurs"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "normalized_name"),
                name="unique_supplier_name_per_company",
            )
        ]

    @staticmethod
    def normalize_name(value):
        return " ".join((value or "").split()).casefold()

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        self.normalized_name = self.normalize_name(self.name)
        if not self.normalized_name:
            raise ValidationError({"name": "La raison sociale est obligatoire."})

    def save(self, *args, **kwargs):
        self.name = " ".join((self.name or "").split())
        self.normalized_name = self.normalize_name(self.name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PurchaseInvoice(models.Model):
    class Status(models.TextChoices):
        IMPORTED = "IMPORTED", "Importée"
        TO_REVIEW = "TO_REVIEW", "À vérifier"
        VALIDATED = "VALIDATED", "Validée"
        REJECTED = "REJECTED", "Rejetée"

    class ExtractionMethod(models.TextChoices):
        MANUAL = "MANUAL", "Saisie manuelle"
        PAPERLESS_OCR = "PAPERLESS_OCR", "OCR Paperless"

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="purchase_invoices",
        verbose_name="société",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
        verbose_name="fournisseur validé",
    )
    supplier_name_raw = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="fournisseur extrait",
    )
    document = models.OneToOneField(
        Document,
        on_delete=models.SET_NULL,
        related_name="purchase_invoice",
        null=True,
        blank=True,
        verbose_name="document PAB",
    )
    paperless_document_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="identifiant Paperless",
    )
    paperless_title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="titre Paperless",
    )
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="nom du fichier d’origine",
    )
    invoice_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="numéro de facture",
    )
    invoice_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="date de facture",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="date d’échéance",
    )
    currency = models.CharField(max_length=3, default="MAD", verbose_name="devise")
    subtotal_ht = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="total brut HT",
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="remise globale",
    )
    net_ht = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="total net HT",
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="total TVA",
    )
    total_ttc = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="total TTC",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TO_REVIEW,
        db_index=True,
        verbose_name="statut",
    )
    extraction_method = models.CharField(
        max_length=20,
        choices=ExtractionMethod.choices,
        default=ExtractionMethod.MANUAL,
        verbose_name="méthode d’extraction",
    )
    extraction_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
        verbose_name="confiance d’extraction",
    )
    raw_ocr_text = models.TextField(blank=True, verbose_name="texte OCR source")
    extraction_notes = models.TextField(blank=True, verbose_name="anomalies d’extraction")
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="validated_purchase_invoices",
        null=True,
        blank=True,
        verbose_name="validée par",
    )
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="validée le")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-invoice_date", "-created_at")
        verbose_name = "facture d’achat"
        verbose_name_plural = "factures d’achat"
        indexes = [
            models.Index(fields=("company", "status")),
            models.Index(fields=("company", "invoice_date")),
            models.Index(fields=("company", "invoice_number")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("company", "paperless_document_id"),
                condition=Q(paperless_document_id__isnull=False),
                name="unique_paperless_purchase_invoice_per_company",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="purchase_invoice_discount_non_negative",
            ),
        ]

    def clean(self):
        super().clean()
        if self.supplier_id and self.company_id:
            if self.supplier.company_id != self.company_id:
                raise ValidationError(
                    {"supplier": "Le fournisseur doit appartenir à la société active."}
                )
        if self.document_id and self.company_id:
            if self.document.company_id != self.company_id:
                raise ValidationError(
                    {"document": "Le document doit appartenir à la société active."}
                )
        if self.due_date and self.invoice_date and self.due_date < self.invoice_date:
            raise ValidationError(
                {"due_date": "L’échéance ne peut pas précéder la date de facture."}
            )

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "MAD").strip().upper()
        return super().save(*args, **kwargs)

    def _line_total(self, field):
        return self.lines.aggregate(total=Sum(field))["total"] or ZERO

    @property
    def line_net_ht_total(self):
        return self._line_total("total_ht")

    @property
    def line_tax_total(self):
        return self._line_total("tax_amount")

    @property
    def line_ttc_total(self):
        return self._line_total("total_ttc")

    @property
    def is_balanced(self):
        expected_values = (self.net_ht, self.tax_amount, self.total_ttc)
        if any(value is None for value in expected_values):
            return False
        differences = (
            abs(self.line_net_ht_total - self.net_ht),
            abs(self.line_tax_total - self.tax_amount),
            abs(self.line_ttc_total - self.total_ttc),
        )
        return all(value <= BALANCE_TOLERANCE for value in differences)

    def __str__(self):
        return self.invoice_number or self.paperless_title or f"Facture {self.pk}"


class PurchaseInvoiceLine(models.Model):
    invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="facture",
    )
    position = models.PositiveIntegerField(verbose_name="ligne")
    reference = models.CharField(max_length=100, blank=True, verbose_name="référence")
    description = models.TextField(verbose_name="désignation")
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=Decimal("1"),
        verbose_name="quantité",
    )
    unit = models.CharField(max_length=30, blank=True, verbose_name="unité")
    unit_price_ht = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=ZERO,
        verbose_name="prix unitaire HT",
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=ZERO,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
        verbose_name="remise %",
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=ZERO,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
        verbose_name="TVA %",
    )
    total_ht = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="total HT",
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="TVA",
    )
    total_ttc = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="total TTC",
    )
    source_text = models.TextField(blank=True, verbose_name="ligne OCR source")
    extraction_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
        verbose_name="confiance",
    )
    verified = models.BooleanField(default=False, verbose_name="vérifiée")

    class Meta:
        ordering = ("position", "pk")
        verbose_name = "ligne de facture d’achat"
        verbose_name_plural = "lignes de facture d’achat"
        constraints = [
            models.UniqueConstraint(
                fields=("invoice", "position"),
                name="unique_purchase_invoice_line_position",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="purchase_invoice_line_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(unit_price_ht__gte=0),
                name="purchase_invoice_line_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_ht__gte=0) & Q(tax_amount__gte=0) & Q(total_ttc__gte=0),
                name="purchase_invoice_line_totals_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.position}. {self.description}"


class PurchaseInvoiceTaxSummary(models.Model):
    invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.CASCADE,
        related_name="tax_summaries",
        verbose_name="facture",
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
        verbose_name="taux de TVA",
    )
    taxable_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="base taxable",
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=ZERO,
        verbose_name="montant TVA",
    )

    class Meta:
        ordering = ("tax_rate",)
        verbose_name = "ventilation TVA"
        verbose_name_plural = "ventilations TVA"
        constraints = [
            models.UniqueConstraint(
                fields=("invoice", "tax_rate"),
                name="unique_purchase_invoice_tax_rate",
            )
        ]

    def __str__(self):
        return f"TVA {self.tax_rate}%"
