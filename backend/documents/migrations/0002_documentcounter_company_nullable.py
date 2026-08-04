import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "companies",
            "0002_alter_company_options_company_contact_company_ice_and_more",
        ),
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="documentcounter",
            name="unique_document_counter_per_year",
        ),
        migrations.AddField(
            model_name="documentcounter",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_counters",
                to="companies.company",
                verbose_name="company",
            ),
        ),
    ]
