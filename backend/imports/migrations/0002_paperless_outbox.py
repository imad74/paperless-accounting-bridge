import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0005_document_pdf_storage"),
        ("imports", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaperlessOutbox",
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
                    "filename",
                    models.CharField(
                        max_length=255,
                        unique=True,
                        verbose_name="filename",
                    ),
                ),
                (
                    "attempt_count",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="attempt count",
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        blank=True,
                        verbose_name="last error",
                    ),
                ),
                (
                    "delivered_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="delivered at",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="created at",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="updated at",
                    ),
                ),
                (
                    "document",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paperless_outbox",
                        to="documents.document",
                        verbose_name="document",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paperless outbox item",
                "verbose_name_plural": "Paperless outbox items",
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(
                        fields=["delivered_at", "created_at"],
                        name="imports_outbox_pending_idx",
                    ),
                ],
            },
        ),
    ]
