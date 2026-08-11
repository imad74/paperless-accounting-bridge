import re

import django.core.validators
from django.db import migrations, models
from django.db.models import Q


PDF_FILENAME_PATTERN = re.compile(r"^(\d{8})\.pdf$", re.IGNORECASE)


def initialize_pdf_counter(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    DocumentFileCounter = apps.get_model(
        "documents",
        "DocumentFileCounter",
    )
    database = schema_editor.connection.alias
    high_water_mark = 0

    stored_filenames = Document.objects.using(database).values_list(
        "stored_filename",
        flat=True,
    )
    for stored_filename in stored_filenames.iterator():
        match = PDF_FILENAME_PATTERN.fullmatch(stored_filename or "")
        if match:
            high_water_mark = max(high_water_mark, int(match.group(1)))

    DocumentFileCounter.objects.using(database).update_or_create(
        key="pdf",
        defaults={"current_number": high_water_mark},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0004_finalize_document_counters"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentFileCounter",
            fields=[
                (
                    "key",
                    models.CharField(
                        default="pdf",
                        editable=False,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "current_number",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[
                            django.core.validators.MaxValueValidator(
                                99_999_999
                            )
                        ],
                        verbose_name="current number",
                    ),
                ),
            ],
            options={
                "verbose_name": "document file counter",
                "verbose_name_plural": "document file counters",
            },
        ),
        migrations.AlterField(
            model_name="document",
            name="original_filename",
            field=models.CharField(
                blank=True,
                default="",
                max_length=255,
                verbose_name="original filename",
            ),
        ),
        migrations.AlterField(
            model_name="document",
            name="stored_filename",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                max_length=255,
                verbose_name="stored filename",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="pdf_file",
            field=models.FileField(
                blank=True,
                max_length=255,
                upload_to="documents/",
                verbose_name="PDF file",
            ),
        ),
        migrations.RunPython(
            initialize_pdf_counter,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="document",
            constraint=models.UniqueConstraint(
                condition=~Q(pdf_file=""),
                fields=("stored_filename",),
                name="unique_non_empty_stored_filename",
            ),
        ),
    ]
