from django.db import migrations
from django.db.models import Count, Max, Min


def assign_counter_companies(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    Document = apps.get_model("documents", "Document")
    DocumentCounter = apps.get_model("documents", "DocumentCounter")
    DocumentType = apps.get_model("documents", "DocumentType")
    database = schema_editor.connection.alias

    companies = list(
        Company.objects.using(database).order_by("pk").values_list("pk", flat=True)
    )
    unresolved_counter_ids = []
    assignments = {}

    counters = DocumentCounter.objects.using(database).filter(
        company_id__isnull=True
    ).order_by("pk")
    for counter in counters.iterator():
        if len(companies) == 1:
            assignments[counter.pk] = companies[0]
            continue

        documents = Document.objects.using(database).filter(
            document_type_id=counter.document_type_id
        )
        year_company_ids = []
        if counter.year:
            year_company_ids = list(
                documents.filter(number__endswith=f"-{counter.year}")
                .order_by()
                .values_list("company_id", flat=True)
                .distinct()
            )

        candidate_company_ids = year_company_ids or list(
            documents.order_by()
            .values_list("company_id", flat=True)
            .distinct()
        )
        if len(candidate_company_ids) == 1:
            assignments[counter.pk] = candidate_company_ids[0]
        else:
            unresolved_counter_ids.append(counter.pk)

    if unresolved_counter_ids:
        ids = ", ".join(str(pk) for pk in unresolved_counter_ids)
        raise RuntimeError(
            "Impossible d’affecter automatiquement la société aux compteurs "
            f"documentaires suivants : {ids}. La migration documents 0002 est "
            "appliquée : renseignez explicitement company_id pour ces compteurs, "
            "puis relancez la migration."
        )

    for counter_id, company_id in assignments.items():
        DocumentCounter.objects.using(database).filter(pk=counter_id).update(
            company_id=company_id
        )

    continuous_type_ids = DocumentType.objects.using(database).filter(
        yearly_reset=False
    ).values_list("pk", flat=True)
    for document_type_id in continuous_type_ids.iterator():
        groups = (
            DocumentCounter.objects.using(database)
            .filter(document_type_id=document_type_id)
            .order_by()
            .values("company_id")
            .annotate(
                keeper_id=Min("pk"),
                high_water_mark=Max("current_number"),
            )
        )
        for group in groups.iterator():
            scoped_counters = DocumentCounter.objects.using(database).filter(
                company_id=group["company_id"],
                document_type_id=document_type_id,
            )
            scoped_counters.exclude(pk=group["keeper_id"]).delete()
            scoped_counters.filter(pk=group["keeper_id"]).update(
                year=0,
                current_number=group["high_water_mark"],
            )

    null_counter_ids = list(
        DocumentCounter.objects.using(database)
        .filter(company_id__isnull=True)
        .values_list("pk", flat=True)
    )
    if null_counter_ids:
        raise RuntimeError(
            "Des compteurs documentaires restent sans société : "
            + ", ".join(str(pk) for pk in null_counter_ids)
        )

    duplicate_scopes = list(
        DocumentCounter.objects.using(database)
        .order_by()
        .values("company_id", "document_type_id", "year")
        .annotate(counter_count=Count("pk"))
        .filter(counter_count__gt=1)
    )
    if duplicate_scopes:
        raise RuntimeError(
            "Plusieurs compteurs utilisent encore la même portée "
            "(société, type, année). Corrigez-les avant de relancer la migration."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_documentcounter_company_nullable"),
    ]

    operations = [
        migrations.RunPython(
            assign_counter_companies,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
