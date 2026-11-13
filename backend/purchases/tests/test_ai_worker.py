from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from companies.models import Company
from purchases.models import PurchaseInvoice, PurchaseInvoiceAnalysisJob
from purchases.services import queue_ai_analysis


@override_settings(PURCHASES_AI_ENABLED=True, OLLAMA_MODEL="qwen2.5vl:3b")
class PurchaseInvoiceAiWorkerTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="AI", name="Acheteur")
        self.user = get_user_model().objects.create_user(username="ai-operator")
        self.invoice = PurchaseInvoice.objects.create(
            company=self.company,
            paperless_document_id=123,
            paperless_title="Facture locale",
        )

    @patch("purchases.management.commands.process_invoice_ai_jobs.reanalyze_invoice_with_ai")
    def test_worker_processes_a_pending_job(self, reanalyze):
        job = queue_ai_analysis(self.invoice, requested_by=self.user)
        reanalyze.return_value = SimpleNamespace(
            model="qwen2.5vl:3b",
            extracted=SimpleNamespace(lines=(1, 2)),
        )

        call_command("process_invoice_ai_jobs", "--once")

        job.refresh_from_db()
        self.assertEqual(job.status, PurchaseInvoiceAnalysisJob.Status.SUCCEEDED)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)
        reanalyze.assert_called_once()

    @patch("purchases.management.commands.process_invoice_ai_jobs.reanalyze_invoice_with_ai")
    def test_worker_records_an_error_without_stopping_the_queue(self, reanalyze):
        job = queue_ai_analysis(self.invoice, requested_by=self.user)
        reanalyze.side_effect = RuntimeError("modèle indisponible")

        call_command("process_invoice_ai_jobs", "--once")

        job.refresh_from_db()
        self.assertEqual(job.status, PurchaseInvoiceAnalysisJob.Status.FAILED)
        self.assertIn("modèle indisponible", job.error_message)
        self.assertIsNotNone(job.finished_at)
