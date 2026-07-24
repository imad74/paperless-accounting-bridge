# Generated for Paperless Accounting Bridge Release 003.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("companies", "0002_alter_company_options_company_contact_company_ice_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyMembership",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("ADMIN", "Administrateur"),
                            ("MANAGER", "Responsable"),
                            ("OPERATOR", "Opérateur"),
                            ("VIEWER", "Lecteur"),
                        ],
                        default="VIEWER",
                        max_length=20,
                        verbose_name="rôle",
                    ),
                ),
                (
                    "active",
                    models.BooleanField(
                        default=True,
                        verbose_name="active",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="créée le",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="modifiée le",
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="companies.company",
                        verbose_name="société",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="company_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "appartenance à une société",
                "verbose_name_plural": "appartenances aux sociétés",
                "ordering": ("company__name", "user__username"),
                "indexes": [
                    models.Index(
                        fields=["user", "active"],
                        name="accounts_cm_user_active_idx",
                    ),
                    models.Index(
                        fields=["company", "active", "role"],
                        name="accounts_cm_company_role_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "company"),
                        name="unique_user_company_membership",
                    ),
                ],
            },
        ),
    ]
