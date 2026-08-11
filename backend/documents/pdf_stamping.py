from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


DEFAULT_MAX_PDF_BYTES = 25 * 1024 * 1024


class PdfProcessingError(ValueError):
    """Raised when an uploaded PDF cannot be safely processed."""


@dataclass(frozen=True)
class PreparedPdf:
    content: bytes
    source_sha256: str
    page_count: int


@dataclass(frozen=True)
class ProcessedPdf:
    content: bytes
    source_sha256: str
    page_count: int


class PdfStampingService:
    """Validate a scanned PDF and print its stored filename on every page."""

    FONT_NAME = "Helvetica-Bold"
    FONT_SIZE = 9
    RIGHT_MARGIN = 18
    TOP_MARGIN = 18
    HORIZONTAL_PADDING = 4
    VERTICAL_PADDING = 3

    @classmethod
    def prepare(
        cls,
        uploaded_file,
        *,
        max_bytes=DEFAULT_MAX_PDF_BYTES,
    ) -> PreparedPdf:
        try:
            uploaded_file.seek(0)
            source_content = uploaded_file.read()
            uploaded_file.seek(0)
        except (AttributeError, OSError) as error:
            raise PdfProcessingError(
                "Le fichier PDF n’a pas pu être lu."
            ) from error

        if not source_content:
            raise PdfProcessingError("Le fichier PDF est vide.")
        if len(source_content) > max_bytes:
            raise PdfProcessingError(
                "Le fichier PDF dépasse la taille maximale autorisée."
            )
        if b"%PDF-" not in source_content[:1024]:
            raise PdfProcessingError(
                "Le fichier transmis n’est pas un PDF valide."
            )

        reader = cls._read_pdf(source_content)
        return PreparedPdf(
            content=source_content,
            source_sha256=sha256(source_content).hexdigest(),
            page_count=len(reader.pages),
        )

    @classmethod
    def process(
        cls,
        uploaded_file,
        stored_filename: str,
        *,
        max_bytes=DEFAULT_MAX_PDF_BYTES,
    ) -> ProcessedPdf:
        return cls.stamp(
            cls.prepare(uploaded_file, max_bytes=max_bytes),
            stored_filename,
        )

    @classmethod
    def stamp(
        cls,
        prepared_pdf: PreparedPdf,
        stored_filename: str,
    ) -> ProcessedPdf:
        reader = cls._read_pdf(prepared_pdf.content)

        writer = PdfWriter()
        for source_page in reader.pages:
            if source_page.rotation:
                source_page.transfer_rotation_to_content()

            width = float(source_page.mediabox.width)
            height = float(source_page.mediabox.height)
            if width <= 0 or height <= 0:
                raise PdfProcessingError(
                    "Une page du PDF possède des dimensions invalides."
                )

            overlay_stream = cls._build_overlay(
                width=width,
                height=height,
                stored_filename=stored_filename,
            )
            overlay_page = PdfReader(overlay_stream).pages[0]
            source_page.merge_page(overlay_page, over=True)
            writer.add_page(source_page)

        output = BytesIO()
        writer.write(output)
        return ProcessedPdf(
            content=output.getvalue(),
            source_sha256=prepared_pdf.source_sha256,
            page_count=len(reader.pages),
        )

    @staticmethod
    def _read_pdf(source_content: bytes) -> PdfReader:
        try:
            reader = PdfReader(BytesIO(source_content), strict=False)
        except (PdfReadError, OSError, ValueError) as error:
            raise PdfProcessingError(
                "Le fichier transmis n’est pas un PDF lisible."
            ) from error

        if reader.is_encrypted:
            raise PdfProcessingError(
                "Les fichiers PDF protégés par un mot de passe ne sont pas acceptés."
            )
        if not reader.pages:
            raise PdfProcessingError("Le fichier PDF ne contient aucune page.")
        return reader

    @classmethod
    def _build_overlay(
        cls,
        *,
        width: float,
        height: float,
        stored_filename: str,
    ) -> BytesIO:
        overlay = BytesIO()
        pdf_canvas = canvas.Canvas(
            overlay,
            pagesize=(width, height),
            pageCompression=1,
            invariant=1,
        )
        text_width = stringWidth(
            stored_filename,
            cls.FONT_NAME,
            cls.FONT_SIZE,
        )
        text_x = width - cls.RIGHT_MARGIN
        text_y = height - cls.TOP_MARGIN - cls.FONT_SIZE
        background_x = (
            text_x - text_width - (2 * cls.HORIZONTAL_PADDING)
        )
        background_y = text_y - cls.VERTICAL_PADDING
        background_width = text_width + (2 * cls.HORIZONTAL_PADDING)
        background_height = cls.FONT_SIZE + (2 * cls.VERTICAL_PADDING)

        pdf_canvas.setFillColorRGB(1, 1, 1)
        pdf_canvas.rect(
            background_x,
            background_y,
            background_width,
            background_height,
            stroke=0,
            fill=1,
        )
        pdf_canvas.setFillColorRGB(0, 0, 0)
        pdf_canvas.setFont(cls.FONT_NAME, cls.FONT_SIZE)
        pdf_canvas.drawRightString(
            text_x - cls.HORIZONTAL_PADDING,
            text_y,
            stored_filename,
        )
        pdf_canvas.save()
        overlay.seek(0)
        return overlay
