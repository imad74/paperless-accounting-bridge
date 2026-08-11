from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
)
from pypdf import PdfReader, PdfWriter

from documents.models import DocumentFileCounter
from documents.pdf_processing import (
    PdfFilenameService,
    PdfProcessingError,
    PdfStampingService,
)

from .pdf_helpers import make_pdf_upload


class TemporaryMediaRootMixin:
    """Keep filename tests isolated from the application's media volume."""

    def setUp(self):
        super().setUp()
        self.temporary_media_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_media_directory.cleanup)
        self.media_settings_override = override_settings(
            MEDIA_ROOT=Path(self.temporary_media_directory.name),
        )
        self.media_settings_override.enable()
        self.addCleanup(self.media_settings_override.disable)


class PdfStampingServiceTests(TestCase):
    def test_filename_is_printed_on_every_page(self):
        processed_pdf = PdfStampingService.process(
            make_pdf_upload(page_count=2),
            "00000001.pdf",
        )

        reader = PdfReader(BytesIO(processed_pdf.content))
        self.assertEqual(processed_pdf.page_count, 2)
        self.assertEqual(len(processed_pdf.source_sha256), 64)
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertIn("00000001.pdf", page.extract_text())

    def test_invalid_pdf_is_rejected(self):
        invalid_pdf = SimpleUploadedFile(
            "scan.pdf",
            b"not a PDF",
            content_type="application/pdf",
        )

        with self.assertRaisesMessage(
            PdfProcessingError,
            "n’est pas un PDF valide",
        ):
            PdfStampingService.process(invalid_pdf, "00000001.pdf")

    def test_rotated_page_is_normalized_before_stamping(self):
        source_pdf = make_pdf_upload()
        reader = PdfReader(source_pdf)
        rotated_page = reader.pages[0]
        rotated_page.rotate(90)
        rotated_output = BytesIO()
        writer = PdfWriter()
        writer.add_page(rotated_page)
        writer.write(rotated_output)
        rotated_upload = SimpleUploadedFile(
            "rotated.pdf",
            rotated_output.getvalue(),
            content_type="application/pdf",
        )

        processed_pdf = PdfStampingService.process(
            rotated_upload,
            "00000001.pdf",
        )

        output_page = PdfReader(BytesIO(processed_pdf.content)).pages[0]
        self.assertEqual(output_page.rotation, 0)
        self.assertIn("00000001.pdf", output_page.extract_text())


class PdfFilenameServiceTests(TemporaryMediaRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        DocumentFileCounter.objects.update_or_create(
            key=DocumentFileCounter.PDF_KEY,
            defaults={"current_number": 0},
        )

    def test_global_sequence_uses_exactly_eight_digits(self):
        first_filename = PdfFilenameService.reserve_filename()
        second_filename = PdfFilenameService.reserve_filename()

        self.assertEqual(first_filename, "00000001.pdf")
        self.assertEqual(second_filename, "00000002.pdf")
        counter = DocumentFileCounter.objects.get(
            key=DocumentFileCounter.PDF_KEY
        )
        self.assertEqual(counter.current_number, 2)

    def test_exhausted_sequence_is_rejected(self):
        DocumentFileCounter.objects.filter(
            key=DocumentFileCounter.PDF_KEY
        ).update(current_number=DocumentFileCounter.MAX_SEQUENCE)

        with self.assertRaisesMessage(
            PdfProcessingError,
            "séquence des noms de fichiers PDF est épuisée",
        ):
            PdfFilenameService.reserve_filename()


@skipUnless(
    connection.vendor == "postgresql",
    "La concurrence des noms PDF doit être testée sous PostgreSQL.",
)
class PdfFilenameConcurrencyTests(
    TemporaryMediaRootMixin,
    TransactionTestCase,
):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        DocumentFileCounter.objects.update_or_create(
            key=DocumentFileCounter.PDF_KEY,
            defaults={"current_number": 0},
        )

    def test_concurrent_reservations_never_duplicate_a_filename(self):
        worker_count = 8
        barrier = Barrier(worker_count)

        def reserve_filename(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return PdfFilenameService.reserve_filename()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            filenames = list(
                executor.map(reserve_filename, range(worker_count))
            )

        self.assertEqual(
            sorted(filenames),
            [f"{sequence:08d}.pdf" for sequence in range(1, 9)],
        )
        self.assertEqual(len(filenames), len(set(filenames)))
