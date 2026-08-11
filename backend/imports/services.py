import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from companies.models import Company
from documents.models import Document, DocumentType
from documents.pdf_processing import (
    DuplicatePdfError,
    PdfFilenameService,
)
from documents.pdf_stamping import PdfProcessingError, PdfStampingService
from documents.services import NumberingService

from .models import ImportJob, PaperlessOutbox


class ScanImportError(RuntimeError):
    """Base exception for automatic scan imports."""


class ScanConfigurationError(ScanImportError):
    """Raised when the scan folder cannot be used safely."""


@dataclass(frozen=True)
class ScanImportResult:
    source_filename: str
    success: bool
    message: str
    document_id: int | None = None
    stored_filename: str = ""


class ScanFolderImporter:
    """Import stable scanned PDFs and enqueue them for Paperless-ngx."""

    SOURCE_NAME = "scan-folder"
    PROCESSING_DIRECTORY_NAME = ".pab-processing"
    ERROR_DIRECTORY_NAME = ".pab-errors"

    def __init__(
        self,
        *,
        input_directory,
        paperless_directory,
        stability_seconds=10,
        company_code="",
        document_type_code="",
        max_pdf_bytes=None,
    ):
        self.input_directory = Path(input_directory)
        self.paperless_directory = Path(paperless_directory)
        self.stability_seconds = max(0, int(stability_seconds))
        self.company_code = (company_code or "").strip()
        self.document_type_code = (document_type_code or "").strip()
        self.max_pdf_bytes = (
            max_pdf_bytes
            if max_pdf_bytes is not None
            else settings.DOCUMENT_PDF_MAX_BYTES
        )
        self.processing_directory = (
            self.input_directory / self.PROCESSING_DIRECTORY_NAME
        )
        self.error_directory = (
            self.input_directory / self.ERROR_DIRECTORY_NAME
        )

    @classmethod
    def from_settings(cls):
        return cls(
            input_directory=settings.SCAN_INPUT_DIRECTORY,
            paperless_directory=settings.SCAN_PAPERLESS_DIRECTORY,
            stability_seconds=settings.SCAN_STABILITY_SECONDS,
            company_code=settings.SCAN_DEFAULT_COMPANY_CODE,
            document_type_code=settings.SCAN_DEFAULT_DOCUMENT_TYPE_CODE,
        )

    def prepare_directories(self):
        try:
            self.input_directory.mkdir(parents=True, exist_ok=True)
            self.paperless_directory.mkdir(parents=True, exist_ok=True)
            self.processing_directory.mkdir(parents=True, exist_ok=True)
            self.error_directory.mkdir(parents=True, exist_ok=True)
            same_directory = os.path.samefile(
                self.input_directory,
                self.paperless_directory,
            )
        except OSError as error:
            raise ScanConfigurationError(
                "Les dossiers de scan et de consommation Paperless "
                "doivent être accessibles."
            ) from error
        if same_directory:
            raise ScanConfigurationError(
                "Le dossier de scan et le dossier de consommation "
                "Paperless doivent être différents."
            )

    def process_ready_files(self) -> list[ScanImportResult]:
        self.prepare_directories()
        self.deliver_pending_files()

        claimed_files = sorted(self.processing_directory.glob("*.pdf"))
        ready_files = self._ready_input_files()
        if not claimed_files and not ready_files:
            return []

        company = self._resolve_company()
        document_type = self._resolve_document_type()
        results = []

        for claimed_file in claimed_files:
            source_filename = self._source_name_from_claim(claimed_file)
            results.append(
                self._process_claimed_file(
                    claimed_file,
                    source_filename=source_filename,
                    source_mtime=claimed_file.stat().st_mtime,
                    company=company,
                    document_type=document_type,
                )
            )

        for source_file in ready_files:
            try:
                source_mtime = source_file.stat().st_mtime
                claimed_file = self._claim(source_file)
            except FileNotFoundError:
                continue
            results.append(
                self._process_claimed_file(
                    claimed_file,
                    source_filename=source_file.name,
                    source_mtime=source_mtime,
                    company=company,
                    document_type=document_type,
                )
            )

        return results

    def deliver_pending_files(self) -> list[tuple[str, bool, str]]:
        self.prepare_directories()
        pending_ids = list(
            PaperlessOutbox.objects.filter(delivered_at__isnull=True)
            .order_by("created_at")
            .values_list("pk", flat=True)
        )
        return [self._deliver_outbox(outbox_id) for outbox_id in pending_ids]

    def _ready_input_files(self) -> list[Path]:
        current_time = time.time()
        ready_files = []
        for candidate in sorted(self.input_directory.iterdir()):
            if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
                continue
            try:
                file_age = current_time - candidate.stat().st_mtime
            except FileNotFoundError:
                continue
            if file_age >= self.stability_seconds:
                ready_files.append(candidate)
        return ready_files

    def _resolve_company(self) -> Company:
        companies = Company.objects.filter(active=True)
        if self.company_code:
            try:
                return companies.get(code__iexact=self.company_code)
            except Company.DoesNotExist:
                raise ScanConfigurationError(
                    "La société configurée pour les scans est introuvable "
                    "ou inactive."
                ) from None

        available_companies = list(companies[:2])
        if len(available_companies) != 1:
            raise ScanConfigurationError(
                "L’import automatique sans code société exige exactement "
                "une société active."
            )
        return available_companies[0]

    def _resolve_document_type(self) -> DocumentType:
        document_types = DocumentType.objects.filter(active=True)
        if self.document_type_code:
            try:
                return document_types.get(
                    code__iexact=self.document_type_code
                )
            except DocumentType.DoesNotExist:
                raise ScanConfigurationError(
                    "Le type documentaire configuré pour les scans est "
                    "introuvable ou inactif."
                ) from None

        available_types = list(document_types[:2])
        if len(available_types) != 1:
            raise ScanConfigurationError(
                "L’import automatique sans code de type exige exactement "
                "un type documentaire actif."
            )
        return available_types[0]

    def _claim(self, source_file: Path) -> Path:
        safe_stem = source_file.stem.replace("--", "-")[:160]
        claimed_name = f"{uuid.uuid4().hex}--{safe_stem}.pdf"
        claimed_file = self.processing_directory / claimed_name
        os.replace(source_file, claimed_file)
        return claimed_file

    @staticmethod
    def _source_name_from_claim(claimed_file: Path) -> str:
        parts = claimed_file.name.split("--", maxsplit=1)
        return parts[1] if len(parts) == 2 else claimed_file.name

    def _process_claimed_file(
        self,
        claimed_file: Path,
        *,
        source_filename: str,
        source_mtime: float,
        company: Company,
        document_type: DocumentType,
    ) -> ScanImportResult:
        started_at = timezone.now()
        job = ImportJob.objects.create(
            filename=source_filename[:255],
            source=self.SOURCE_NAME,
        )
        document = None
        database_saved = False

        try:
            with claimed_file.open("rb") as pdf_stream:
                prepared_pdf = PdfStampingService.prepare(
                    pdf_stream,
                    max_bytes=self.max_pdf_bytes,
                )
            if Document.objects.filter(
                sha256=prepared_pdf.source_sha256
            ).exists():
                raise DuplicatePdfError(
                    "Ce fichier PDF a déjà été enregistré."
                )

            stored_filename = PdfFilenameService.reserve_filename()
            processed_pdf = PdfStampingService.stamp(
                prepared_pdf,
                stored_filename,
            )
            document_date = datetime.fromtimestamp(
                source_mtime,
                tz=timezone.get_current_timezone(),
            ).date()
            document = Document(
                title=(Path(source_filename).stem or "Document scanné")[:255],
                company=company,
                document_type=document_type,
                original_filename=source_filename[:255],
                stored_filename=stored_filename,
                document_date=document_date,
                sha256=processed_pdf.source_sha256,
                status=Document.Status.NEW,
            )
            document.pdf_file = ContentFile(
                processed_pdf.content,
                name=stored_filename,
            )

            with transaction.atomic():
                if Document.objects.filter(
                    sha256=processed_pdf.source_sha256
                ).exists():
                    raise DuplicatePdfError(
                        "Ce fichier PDF a déjà été enregistré."
                    )
                document.number = NumberingService.generate(
                    company=company,
                    document_type_code=document_type.code,
                    generation_date=document_date,
                )
                document.save()
                outbox = PaperlessOutbox.objects.create(
                    document=document,
                    filename=stored_filename,
                )
            database_saved = True

            _, delivered, delivery_message = self._deliver_outbox(outbox.pk)
            warning_count = 0 if delivered else 1
            message = (
                f"Document {document.number} créé avec {stored_filename}."
            )
            if not delivered:
                message = f"{message} {delivery_message}"
            try:
                claimed_file.unlink(missing_ok=True)
            except OSError:
                warning_count += 1
                message = (
                    f"{message} Le scan source n’a pas pu être supprimé "
                    "du dossier de traitement."
                )
            self._finish_job(
                job,
                started_at=started_at,
                success=True,
                message=message,
                processed_documents=1,
                warning_count=warning_count,
            )
            return ScanImportResult(
                source_filename=source_filename,
                success=True,
                message=message,
                document_id=document.pk,
                stored_filename=stored_filename,
            )
        except (
            DuplicatePdfError,
            IntegrityError,
            OSError,
            PdfProcessingError,
            ValueError,
        ) as error:
            if (
                document is not None
                and not database_saved
                and document.pdf_file.name
            ):
                try:
                    document.pdf_file.storage.delete(document.pdf_file.name)
                except OSError:
                    pass
            message = str(error) or "L’import automatique a échoué."
            try:
                self._move_to_error(claimed_file, source_filename)
            except OSError:
                message = (
                    f"{message} Le scan n’a pas pu être déplacé dans "
                    "le dossier des erreurs."
                )
            self._finish_job(
                job,
                started_at=started_at,
                success=False,
                message=message,
                failed_documents=1,
            )
            return ScanImportResult(
                source_filename=source_filename,
                success=False,
                message=message,
            )

    @transaction.atomic
    def _deliver_outbox(self, outbox_id: int) -> tuple[str, bool, str]:
        try:
            outbox = (
                PaperlessOutbox.objects.select_for_update()
                .select_related("document")
                .get(pk=outbox_id)
            )
        except PaperlessOutbox.DoesNotExist:
            return "", False, "Élément Paperless introuvable."
        if outbox.delivered_at is not None:
            return outbox.filename, True, "Déjà remis à Paperless."

        outbox.attempt_count += 1
        try:
            self._copy_document_to_paperless(outbox)
        except (OSError, ScanImportError) as error:
            outbox.last_error = str(error)
            outbox.save(
                update_fields=("attempt_count", "last_error", "updated_at")
            )
            return outbox.filename, False, (
                "Le fichier reste en attente de remise à Paperless."
            )

        outbox.delivered_at = timezone.now()
        outbox.last_error = ""
        outbox.save(
            update_fields=(
                "attempt_count",
                "delivered_at",
                "last_error",
                "updated_at",
            )
        )
        return outbox.filename, True, "Fichier remis à Paperless."

    def _copy_document_to_paperless(self, outbox: PaperlessOutbox):
        destination = self.paperless_directory / outbox.filename
        if destination.exists():
            if self._same_content(outbox.document.pdf_file, destination):
                return
            raise ScanImportError(
                f"Le fichier Paperless {outbox.filename} existe déjà "
                "avec un contenu différent."
            )

        temporary_destination = self.paperless_directory / (
            f".{outbox.filename}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with outbox.document.pdf_file.open("rb") as source_stream:
                with temporary_destination.open("xb") as target_stream:
                    shutil.copyfileobj(source_stream, target_stream)
                    target_stream.flush()
                    os.fsync(target_stream.fileno())
            if destination.exists():
                if self._same_content(
                    outbox.document.pdf_file,
                    destination,
                ):
                    return
                raise ScanImportError(
                    f"Le fichier Paperless {outbox.filename} a été créé "
                    "simultanément avec un contenu différent."
                )
            os.replace(temporary_destination, destination)
        finally:
            temporary_destination.unlink(missing_ok=True)

    @staticmethod
    def _same_content(document_file, filesystem_path: Path) -> bool:
        with document_file.open("rb") as document_stream:
            document_digest = ScanFolderImporter._stream_sha256(
                document_stream
            )
        with filesystem_path.open("rb") as filesystem_stream:
            filesystem_digest = ScanFolderImporter._stream_sha256(
                filesystem_stream
            )
        return document_digest == filesystem_digest

    @staticmethod
    def _stream_sha256(stream) -> str:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()

    def _move_to_error(self, claimed_file: Path, source_filename: str):
        if not claimed_file.exists():
            return
        safe_name = Path(source_filename).name.replace("--", "-")[:180]
        error_file = self.error_directory / (
            f"{uuid.uuid4().hex}--{safe_name}"
        )
        os.replace(claimed_file, error_file)

    @staticmethod
    def _finish_job(
        job: ImportJob,
        *,
        started_at,
        success,
        message,
        processed_documents=0,
        failed_documents=0,
        warning_count=0,
    ):
        finished_at = timezone.now()
        job.success = success
        job.message = message
        job.execution_log = message
        job.processed_documents = processed_documents
        job.failed_documents = failed_documents
        job.warning_count = warning_count
        job.finished_at = finished_at
        job.duration = finished_at - started_at
        job.save(
            update_fields=(
                "success",
                "message",
                "execution_log",
                "processed_documents",
                "failed_documents",
                "warning_count",
                "finished_at",
                "duration",
            )
        )
