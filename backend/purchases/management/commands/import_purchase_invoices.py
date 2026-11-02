from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from companies.models import Company
from documents.paperless_api import PaperlessApiClient, PaperlessApiError
from purchases.models import InvoiceNature, PurchaseInvoice
from purchases.services import PurchaseInvoiceImportService


class Command(BaseCommand):
    help = (
        "Importe en lot les factures Paperless dans la base des achats. "
        "Par défaut, seules les factures d’achat de marchandises sont enregistrées ; "
        "locations, services, frais et factures de vente sont ignorés."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help="Code de la société (obligatoire s’il existe plusieurs sociétés).",
        )
        parser.add_argument(
            "--nature",
            action="append",
            choices=InvoiceNature.values,
            help=(
                "Nature à importer ; option répétable. "
                "Par défaut : MARCHANDISES uniquement."
            ),
        )
        parser.add_argument(
            "--from-id",
            type=int,
            default=None,
            help="Ne traite que les documents Paperless dont l’identifiant est supérieur ou égal.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Nombre maximal de documents Paperless à analyser.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyse et compte sans rien enregistrer.",
        )

    def handle(self, *args, **options):
        company = self._company(options["company"])
        natures = set(options["nature"] or [InvoiceNature.GOODS])
        dry_run = options["dry_run"]
        try:
            client = PaperlessApiClient()
        except PaperlessApiError as error:
            raise CommandError(str(error)) from error
        service = PurchaseInvoiceImportService(client=client)
        already = set(
            PurchaseInvoice.objects.filter(company=company)
            .exclude(paperless_document_id=None)
            .values_list("paperless_document_id", flat=True)
        )

        by_nature, outcome = Counter(), Counter()
        last_id = None
        self.stdout.write(
            f"Société : {company.code} — natures importées : {', '.join(sorted(natures))}"
            + (" — SIMULATION, rien n’est enregistré" if dry_run else "")
        )
        try:
            for analysed, document in enumerate(
                client.iter_documents(min_id=options["from_id"]), start=1
            ):
                if options["limit"] and analysed > options["limit"]:
                    break
                last_id = document.id
                if analysed % 200 == 0:
                    self.stdout.write(f"  {analysed} documents analysés…")
                if document.id in already:
                    outcome["déjà importées"] += 1
                    continue
                _extracted, _supplier, nature = service.analyse(
                    company=company, paperless_document=document
                )
                by_nature[nature] += 1
                if nature not in natures:
                    outcome["ignorées (autre nature)"] += 1
                    continue
                if dry_run:
                    outcome["à importer"] += 1
                    continue
                invoice, created = service.import_document(
                    company=company,
                    paperless_document=document,
                    allowed_natures=natures,
                )
                outcome["importées" if created else "déjà importées"] += 1
        except PaperlessApiError as error:
            self.stderr.write(self.style.ERROR(str(error)))
            if last_id:
                self.stderr.write(f"Reprendre avec --from-id {last_id}")

        self.stdout.write("Nature détectée (documents non encore importés) :")
        for value, label in InvoiceNature.choices:
            if by_nature[value]:
                self.stdout.write(f"  {label} : {by_nature[value]}")
        self.stdout.write("Résultat :")
        for key, count in sorted(outcome.items()):
            self.stdout.write(f"  {key} : {count}")
        if last_id:
            self.stdout.write(f"Dernier document Paperless analysé : #{last_id}")
        self.stdout.write(
            self.style.SUCCESS(
                "Terminé. Les factures importées restent « À vérifier » jusqu’à validation."
            )
        )

    @staticmethod
    def _company(code):
        if code:
            company = Company.objects.filter(code__iexact=code).first()
            if company is None:
                raise CommandError(f"Société introuvable : {code}")
            return company
        companies = list(Company.objects.all()[:2])
        if len(companies) != 1:
            raise CommandError("Précisez la société avec --company CODE.")
        return companies[0]
