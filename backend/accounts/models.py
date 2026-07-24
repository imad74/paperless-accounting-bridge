from django.conf import settings
from django.db import models

from companies.models import Company


class CompanyMembership(models.Model):
    """Associates a user with a company and an application role."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrateur"
        MANAGER = "MANAGER", "Responsable"
        OPERATOR = "OPERATOR", "Opérateur"
        VIEWER = "VIEWER", "Lecteur"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_memberships",
        verbose_name="utilisateur",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="société",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        verbose_name="rôle",
    )
    active = models.BooleanField(
        default=True,
        verbose_name="active",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="créée le",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="modifiée le",
    )

    class Meta:
        ordering = ("company__name", "user__username")
        verbose_name = "appartenance à une société"
        verbose_name_plural = "appartenances aux sociétés"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "company"),
                name="unique_user_company_membership",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "active"),
                name="accounts_cm_user_active_idx",
            ),
            models.Index(
                fields=("company", "active", "role"),
                name="accounts_cm_company_role_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.company} ({self.get_role_display()})"
