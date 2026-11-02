from django.core.management.base import BaseCommand

from purchases.management.commands.import_purchase_invoices import Command as ImportCommand
from purchases.models import PurchaseInvoice
from purchases.services import link_invoices_to_suppliers


class Command(BaseCommand):
    help = (
        "Rattache à leur fournisseur de l’annuaire les factures importées qui n’en ont pas, "
        "d’après l’ICE lu sur la facture."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Code de la société.")

    def handle(self, *args, **options):
        company = ImportCommand._company(options["company"])
        linked = link_invoices_to_suppliers(company)
        remaining = PurchaseInvoice.objects.filter(company=company, supplier__isnull=True)
        self.stdout.write(f"  factures rattachées : {linked}")
        self.stdout.write(f"  factures encore sans fournisseur : {remaining.count()}")
        self.stdout.write(
            f"    dont sans ICE lisible : {remaining.filter(supplier_ice_raw='').count()}"
        )
        self.stdout.write(self.style.SUCCESS("Terminé."))
