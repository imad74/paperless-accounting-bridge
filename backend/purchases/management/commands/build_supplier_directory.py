from django.core.management.base import BaseCommand, CommandError

from documents.paperless_api import PaperlessApiClient, PaperlessApiError
from purchases.directory import SupplierDirectoryBuilder
from purchases.management.commands.import_purchase_invoices import Command as ImportCommand
from purchases.models import InvoiceNature
from purchases.services import extractor_for_company


class Command(BaseCommand):
    help = (
        "Analyse toute l’archive Paperless et constitue la base des fournisseurs : "
        "ICE, nom proposé, nature détectée, nombre de factures, période et total. "
        "La nature validée et l’activité saisies dans PAB ne sont jamais modifiées."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Code de la société.")
        parser.add_argument(
            "--limit", type=int, default=None, help="Nombre maximal de documents à analyser."
        )
        parser.add_argument(
            "--min-documents",
            type=int,
            default=1,
            help="Ne crée que les fournisseurs présents sur au moins N documents (défaut : 1).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Affiche le résultat sans rien enregistrer."
        )
        parser.add_argument(
            "--auto-validate",
            action="store_true",
            help=(
                "Valide automatiquement la nature détectée des fournisseurs "
                "(les validations manuelles ne sont jamais modifiées)."
            ),
        )
        parser.add_argument(
            "--auto-min-documents",
            type=int,
            default=1,
            help="Nombre minimal de documents pour une validation automatique (défaut : 1).",
        )
        parser.add_argument(
            "--top", type=int, default=30, help="Nombre de fournisseurs affichés dans le résumé."
        )

    def handle(self, *args, **options):
        company = ImportCommand._company(options["company"])
        if not company.ice:
            raise CommandError(
                "L’ICE de la société n’est pas renseigné : il est indispensable pour ne pas "
                "le confondre avec celui des fournisseurs."
            )
        try:
            client = PaperlessApiClient()
        except PaperlessApiError as error:
            raise CommandError(str(error)) from error

        builder = SupplierDirectoryBuilder(company=company, extractor=extractor_for_company(company))
        analysed = 0
        try:
            for analysed, document in enumerate(client.iter_documents(), start=1):
                if options["limit"] and analysed > options["limit"]:
                    analysed -= 1
                    break
                builder.add_document(document)
                if analysed % 500 == 0:
                    self.stdout.write(f"  {analysed} documents analysés…")
        except PaperlessApiError as error:
            raise CommandError(f"{error} (après {analysed} documents ; rien n’a été enregistré)") from error

        if options["dry_run"]:
            groups = builder.grouped()
            groups = [g for g in groups if g.documents >= options["min_documents"]]
            self.stdout.write(self.style.WARNING("SIMULATION : rien n’est enregistré."))
        else:
            groups = builder.save(
                min_documents=options["min_documents"],
                auto_validate=options["auto_validate"],
                auto_min_documents=options["auto_min_documents"],
            )

        labels = dict(InvoiceNature.choices)
        by_nature = {}
        for stats in groups:
            by_nature[stats.detected_nature] = by_nature.get(stats.detected_nature, 0) + 1
        self.stdout.write(f"Documents analysés : {analysed}")
        for key, count in sorted(builder.outcome.items()):
            self.stdout.write(f"  {key} : {count}")
        self.stdout.write(f"Fournisseurs distincts : {len(groups)}")
        for value, label in InvoiceNature.choices:
            if by_nature.get(value):
                self.stdout.write(f"  {label} : {by_nature[value]}")
        self.stdout.write(f"Principaux fournisseurs (par nombre de documents) :")
        for stats in sorted(groups, key=lambda g: -g.documents)[: options["top"]]:
            self.stdout.write(
                f"  {stats.ice}  {stats.documents:>4} doc.  "
                f"{labels.get(stats.detected_nature, stats.detected_nature)[:22]:22}  "
                f"{(stats.suggested_name or '—')[:40]}"
            )
        self.stdout.write(self.style.SUCCESS("Terminé."))
