import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_migrate_document_counters"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documentcounter",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_counters",
                to="companies.company",
                verbose_name="company",
            ),
        ),
        migrations.AlterModelOptions(
            name="documentcounter",
            options={
                "ordering": ["company__code", "document_type__code", "year"],
                "verbose_name": "document counter",
                "verbose_name_plural": "document counters",
            },
        ),
        migrations.AddConstraint(
            model_name="documentcounter",
            constraint=models.UniqueConstraint(
                fields=("company", "document_type", "year"),
                name="unique_document_counter_scope",
            ),
        ),
    ]
