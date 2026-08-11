from django.core.files.storage import default_storage
from django.db import transaction

from .models import Document, DocumentFileCounter
from .pdf_stamping import (
    PdfProcessingError,
    PdfStampingService,
)


class DuplicatePdfError(PdfProcessingError):
    """Raised when the uploaded PDF already exists in the database."""


class PdfFilenameService:
    """Reserve globally unique eight-digit PDF filenames."""

    STORAGE_DIRECTORY = "documents"

    @classmethod
    @transaction.atomic
    def reserve_filename(cls) -> str:
        counter, _ = (
            DocumentFileCounter.objects.select_for_update().get_or_create(
                key=DocumentFileCounter.PDF_KEY,
                defaults={"current_number": 0},
            )
        )
        sequence = counter.current_number + 1

        while sequence <= DocumentFileCounter.MAX_SEQUENCE:
            filename = f"{sequence:08d}.pdf"
            storage_name = f"{cls.STORAGE_DIRECTORY}/{filename}"
            if (
                not Document.objects.filter(
                    stored_filename=filename
                ).exists()
                and not default_storage.exists(storage_name)
            ):
                counter.current_number = sequence
                counter.save(update_fields=("current_number",))
                return filename
            sequence += 1

        raise PdfProcessingError(
            "La séquence des noms de fichiers PDF est épuisée."
        )
