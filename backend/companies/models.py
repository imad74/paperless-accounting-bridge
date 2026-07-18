from django.db import models


class Company(models.Model):
    """Represents a business partner or client in the accounting workflow."""

    name = models.CharField(max_length=255, unique=True, verbose_name="name")
    code = models.CharField(max_length=20, unique=True, verbose_name="code")
    address = models.TextField(blank=True, verbose_name="address")
    city = models.CharField(max_length=255, blank=True, verbose_name="city")
    country = models.CharField(max_length=255, blank=True, verbose_name="country")
    phone = models.CharField(max_length=50, blank=True, verbose_name="phone")
    email = models.EmailField(blank=True, verbose_name="email")
    active = models.BooleanField(default=True, verbose_name="active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="created at")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="updated at")

    class Meta:
        verbose_name = "company"
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
