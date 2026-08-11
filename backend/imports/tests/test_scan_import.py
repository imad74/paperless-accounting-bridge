from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader

from companies.models import Company
from documents.models import Document, DocumentType
from documents.tests.pdf_helpers import make_pdf_upload
from imports.models import ImportJob, PaperlessOutbox
from imports.services import ScanConfigurationError, ScanFolderImporter


class ScanFolderImporterTests(TestCase):
    def setUp(self):
        super().setUp()
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root_directory = Path(self.temporary_directory.name)
        self.input_directory = self.root_directory / "scan"
        self.paperless_directory = self.root_directory / "paperless"
        self.media_directory = self.root_directory / "media"
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.company = Company.objects.create(
            code="DEL",
            name="DELIGHT EVENT",
        )
        self.document_type = DocumentType.objects.create(
            code="FN",
            name="Facture",
            prefix="FN",
        )
        self.importer = ScanFolderImporter(
            input_directory=self.input_directory,
            paperless_directory=self.paperless_directory,
            stability_seconds=0,
        )

    def write_scan(self, filename="scan-001.pdf", marker="Scan unique"):
        self.input_directory.mkdir(parents=True, exist_ok=True)
        uploaded_pdf = make_pdf_upload(name=filename, marker=marker)
        scan_path = self.input_directory / filename
        scan_path.write_bytes(uploaded_pdf.read())
        return scan_path

    def test_single_active_company_and_type_are_selected_automatically(self):
        source_path = self.write_scan()

        results = self.importer.process_ready_files()

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success, results[0].message)
        document = Document.objects.get()
        self.assertEqual(document.company, self.company)
        self.assertEqual(document.document_type, self.document_type)
        self.assertEqual(document.original_filename, "scan-001.pdf")
        self.assertEqual(document.stored_filename, "00000001.pdf")
        self.assertEqual(
            document.number,
            f"FN-DEL-000001-{timezone.localdate().year}",
        )
        self.assertFalse(source_path.exists())

        paperless_pdf = self.paperless_directory / "00000001.pdf"
        self.assertTrue(paperless_pdf.exists())
        stamped_reader = PdfReader(BytesIO(paperless_pdf.read_bytes()))
        self.assertIn(
            "00000001.pdf",
            stamped_reader.pages[0].extract_text(),
        )
        outbox = PaperlessOutbox.objects.get(document=document)
        self.assertIsNotNone(outbox.delivered_at)
        self.assertEqual(outbox.attempt_count, 1)
        job = ImportJob.objects.get()
        self.assertTrue(job.success)
        self.assertEqual(job.processed_documents, 1)

    def test_duplicate_scan_is_moved_to_errors_without_new_document(self):
        first_source = self.write_scan(marker="Même contenu")
        source_content = first_source.read_bytes()
        first_result = self.importer.process_ready_files()[0]
        (self.paperless_directory / first_result.stored_filename).unlink()
        second_source = self.input_directory / "copie.pdf"
        second_source.write_bytes(source_content)

        second_result = self.importer.process_ready_files()[0]

        self.assertFalse(second_result.success)
        self.assertIn("déjà été enregistré", second_result.message)
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(ImportJob.objects.count(), 2)
        self.assertEqual(
            len(list(self.importer.error_directory.glob("*.pdf"))),
            1,
        )

    def test_invalid_pdf_is_isolated_and_logged(self):
        self.input_directory.mkdir(parents=True, exist_ok=True)
        invalid_scan = self.input_directory / "invalide.pdf"
        invalid_scan.write_bytes(b"not a PDF")

        result = self.importer.process_ready_files()[0]

        self.assertFalse(result.success)
        self.assertFalse(invalid_scan.exists())
        self.assertEqual(Document.objects.count(), 0)
        job = ImportJob.objects.get()
        self.assertFalse(job.success)
        self.assertEqual(job.failed_documents, 1)
        self.assertEqual(
            len(list(self.importer.error_directory.glob("*.pdf"))),
            1,
        )

    def test_recent_scan_waits_until_it_is_stable(self):
        source_path = self.write_scan()
        cautious_importer = ScanFolderImporter(
            input_directory=self.input_directory,
            paperless_directory=self.paperless_directory,
            stability_seconds=60,
        )

        results = cautious_importer.process_ready_files()

        self.assertEqual(results, [])
        self.assertTrue(source_path.exists())
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(ImportJob.objects.count(), 0)

    def test_ambiguous_company_configuration_leaves_scan_untouched(self):
        Company.objects.create(code="OTHER", name="Autre société")
        source_path = self.write_scan()

        with self.assertRaisesMessage(
            ScanConfigurationError,
            "exactement une société active",
        ):
            self.importer.process_ready_files()

        self.assertTrue(source_path.exists())
        self.assertEqual(ImportJob.objects.count(), 0)

    def test_failed_paperless_delivery_is_retried_from_the_outbox(self):
        self.write_scan()
        with patch.object(
            self.importer,
            "_copy_document_to_paperless",
            side_effect=OSError("Paperless indisponible"),
        ):
            result = self.importer.process_ready_files()[0]

        self.assertTrue(result.success)
        outbox = PaperlessOutbox.objects.get()
        self.assertIsNone(outbox.delivered_at)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(ImportJob.objects.get().warning_count, 1)

        deliveries = self.importer.deliver_pending_files()

        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0][1])
        outbox.refresh_from_db()
        self.assertIsNotNone(outbox.delivered_at)
        self.assertEqual(outbox.attempt_count, 2)
        self.assertTrue(
            (self.paperless_directory / "00000001.pdf").exists()
        )

    def test_existing_different_paperless_file_is_never_overwritten(self):
        self.write_scan()
        self.paperless_directory.mkdir(parents=True, exist_ok=True)
        destination = self.paperless_directory / "00000001.pdf"
        existing_content = b"existing Paperless content"
        destination.write_bytes(existing_content)

        result = self.importer.process_ready_files()[0]

        self.assertTrue(result.success)
        self.assertEqual(destination.read_bytes(), existing_content)
        outbox = PaperlessOutbox.objects.get()
        self.assertIsNone(outbox.delivered_at)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertIn("contenu différent", outbox.last_error)
        self.assertEqual(ImportJob.objects.get().warning_count, 1)

    def test_input_and_paperless_directories_must_be_different(self):
        unsafe_importer = ScanFolderImporter(
            input_directory=self.input_directory,
            paperless_directory=self.input_directory,
            stability_seconds=0,
        )

        with self.assertRaisesMessage(
            ScanConfigurationError,
            "doivent être différents",
        ):
            unsafe_importer.prepare_directories()


class WatchScanFolderCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root_directory = Path(self.temporary_directory.name)
        Company.objects.create(code="DEL", name="DELIGHT EVENT")
        DocumentType.objects.create(
            code="FN",
            name="Facture",
            prefix="FN",
        )

    def test_once_processes_available_scan_and_exits(self):
        input_directory = self.root_directory / "scan"
        paperless_directory = self.root_directory / "paperless"
        media_directory = self.root_directory / "media"
        input_directory.mkdir()
        scan_upload = make_pdf_upload(marker="Commande")
        (input_directory / "commande.pdf").write_bytes(scan_upload.read())
        stdout = StringIO()

        with override_settings(
            MEDIA_ROOT=media_directory,
            SCAN_INPUT_DIRECTORY=input_directory,
            SCAN_PAPERLESS_DIRECTORY=paperless_directory,
            SCAN_STABILITY_SECONDS=0,
            SCAN_DEFAULT_COMPANY_CODE="",
            SCAN_DEFAULT_DOCUMENT_TYPE_CODE="",
        ):
            call_command("watch_scan_folder", "--once", stdout=stdout)

        self.assertEqual(Document.objects.count(), 1)
        self.assertTrue((paperless_directory / "00000001.pdf").exists())
        self.assertIn("00000001.pdf", stdout.getvalue())
