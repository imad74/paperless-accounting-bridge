from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company


class CompanyMembership(models.Model):
    """Associates a user with a company and an application role."""

    LAST_ACTIVE_ADMIN_ERROR = (
        "Le dernier administrateur actif de la société ne peut pas être "
        "suspendu, rétrogradé ou supprimé."
    )

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

    def clean(self):
        super().clean()
        if self.pk is None:
            return

        previous = type(self).objects.filter(pk=self.pk).values(
            "active",
            "role",
            "company_id",
        ).first()
        if previous is None:
            return

        was_active_admin = (
            previous["active"]
            and previous["role"] == self.Role.ADMIN
        )
        remains_active_admin = (
            self.active
            and self.role == self.Role.ADMIN
            and self.company_id == previous["company_id"]
        )
        if was_active_admin and not remains_active_admin:
            another_admin_exists = type(self).objects.filter(
                company_id=previous["company_id"],
                role=self.Role.ADMIN,
                active=True,
            ).exclude(pk=self.pk).exists()
            if not another_admin_exists:
                raise ValidationError(self.LAST_ACTIVE_ADMIN_ERROR)

    def is_last_active_administrator(self) -> bool:
        if (
            self.pk is None
            or not self.active
            or self.role != self.Role.ADMIN
        ):
            return False
        return not type(self).objects.filter(
            company_id=self.company_id,
            role=self.Role.ADMIN,
            active=True,
        ).exclude(pk=self.pk).exists()
