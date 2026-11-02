from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from purchases.management.commands.import_purchase_invoices import Command as ImportCommand
from purchases.models import InvoiceNature, Supplier


class Command(BaseCommand):
    help = (
        "Valide automatiquement la nature détectée des fournisseurs déjà présents dans "
        "l’annuaire, sans réanalyser l’archive. Les natures validées à la main ne sont "
        "jamais modifiées ; les validations automatiques sont recalculées."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Code de la société.")
        parser.add_argument(
            "--min-documents",
            type=int,
            default=1,
            help="Nombre minimal de documents Paperless pour valider (défaut : 1).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Compte sans rien enregistrer."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        company = ImportCommand._company(options["company"])
        outcome, by_nature = Counter(), Counter()
        for supplier in Supplier.objects.select_for_update().filter(company=company):
            if supplier.default_nature and supplier.nature_validation != Supplier.NatureValidation.AUTO:
                outcome["validées à la main (inchangées)"] += 1
                continue
            changed = supplier.auto_validate_nature(min_documents=options["min_documents"])
            if supplier.nature_validation == Supplier.NatureValidation.AUTO:
                by_nature[supplier.default_nature] += 1
                outcome["validées automatiquement"] += 1
                if changed:
                    outcome["dont nouvelles ou modifiées"] += 1
            else:
                outcome["restent à valider (nature indéterminée ou trop peu de documents)"] += 1
            if changed and not options["dry_run"]:
                supplier.save(update_fields=["default_nature", "nature_validation", "updated_at"])
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("SIMULATION : rien n’est enregistré."))
        for key, count in sorted(outcome.items()):
            self.stdout.write(f"  {key} : {count}")
        labels = dict(InvoiceNature.choices)
        for nature, count in by_nature.most_common():
            self.stdout.write(f"    {labels.get(nature, nature)} : {count}")
        self.stdout.write(self.style.SUCCESS("Terminé."))
