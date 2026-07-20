from django.db import models


class Company(models.Model):
    code = models.CharField(
        max_length=20,
        unique=True,
    )

    name = models.CharField(
        max_length=255,
        unique=True,
    )

    ice = models.CharField(
        max_length=30,
        blank=True,
    )

    if_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="IF",
    )

    rc = models.CharField(
        max_length=30,
        blank=True,
    )

    patente = models.CharField(
        max_length=30,
        blank=True,
    )

    address = models.TextField(
        blank=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
    )

    country = models.CharField(
        max_length=100,
        default="Maroc",
    )

    contact = models.CharField(
        max_length=150,
        blank=True,
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    website = models.URLField(
        blank=True,
    )

    active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self):
        return f"{self.code} - {self.name}"