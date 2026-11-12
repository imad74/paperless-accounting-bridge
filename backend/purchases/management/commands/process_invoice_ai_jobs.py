import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from purchases.models import PurchaseInvoiceAnalysisJob
from purchases.services import reanalyze_invoice_with_ai


class Command(BaseCommand):
    help = "Traite en arrière-plan la file locale d’analyse IA des factures."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Traite la file puis quitte.")
        parser.add_argument("--poll-seconds", type=float, default=5)

    def handle(self, *args, **options):
        self._recover_stale_jobs()
        while True:
            job = self._claim_next_job()
            if job is None:
                if options["once"]:
                    return
                time.sleep(max(options["poll_seconds"], 1))
                continue
            self._process(job)

    @staticmethod
    def _recover_stale_jobs():
        cutoff = timezone.now() - timedelta(hours=2)
        PurchaseInvoiceAnalysisJob.objects.filter(
            status=PurchaseInvoiceAnalysisJob.Status.RUNNING,
            started_at__lt=cutoff,
        ).update(
            status=PurchaseInvoiceAnalysisJob.Status.PENDING,
            started_at=None,
            error_message="Traitement interrompu puis remis en file.",
        )

    @staticmethod
    @transaction.atomic
    def _claim_next_job():
        job = (
            PurchaseInvoiceAnalysisJob.objects.select_for_update(skip_locked=True)
            .select_related("invoice", "invoice__company")
            .filter(status=PurchaseInvoiceAnalysisJob.Status.PENDING)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        job.status = PurchaseInvoiceAnalysisJob.Status.RUNNING
        job.started_at = timezone.now()
        job.finished_at = None
        job.error_message = ""
        job.save(
            update_fields=("status", "started_at", "finished_at", "error_message", "updated_at")
        )
        return job

    def _process(self, job):
        self.stdout.write(f"Analyse locale de la facture #{job.invoice_id}…")
        try:
            result = reanalyze_invoice_with_ai(job.invoice)
        except Exception as error:
            job.status = PurchaseInvoiceAnalysisJob.Status.FAILED
            job.error_message = str(error)[:4000]
            self.stderr.write(self.style.ERROR(f"Facture #{job.invoice_id} : {error}"))
        else:
            job.status = PurchaseInvoiceAnalysisJob.Status.SUCCEEDED
            job.model_name = result.model
            job.error_message = ""
            self.stdout.write(
                self.style.SUCCESS(
                    f"Facture #{job.invoice_id} : {len(result.extracted.lines)} ligne(s)."
                )
            )
        job.finished_at = timezone.now()
        job.save(
            update_fields=("status", "model_name", "error_message", "finished_at", "updated_at")
        )
