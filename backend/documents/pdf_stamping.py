from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.utils import ImageReader
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
    """Validate a scanned PDF and raster-stamp its filename on every page."""

    FONT_SIZE = 9
    RIGHT_MARGIN = 18
    TOP_MARGIN = 18
    HORIZONTAL_PADDING = 4
    VERTICAL_PADDING = 3
    RASTER_SCALE = 4

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
        stamp_image, stamp_width, stamp_height = cls._build_stamp_image(
            cls._stamp_label(stored_filename),
        )
        overlay = BytesIO()
        pdf_canvas = canvas.Canvas(
            overlay,
            pagesize=(width, height),
            pageCompression=1,
            invariant=1,
        )
        pdf_canvas.drawImage(
            ImageReader(stamp_image),
            width - cls.RIGHT_MARGIN - stamp_width,
            height - cls.TOP_MARGIN - stamp_height,
            width=stamp_width,
            height=stamp_height,
            preserveAspectRatio=True,
            mask=None,
        )
        pdf_canvas.save()
        overlay.seek(0)
        return overlay

    @staticmethod
    def _stamp_label(stored_filename: str) -> str:
        if stored_filename.lower().endswith(".pdf"):
            return stored_filename[:-4]
        return stored_filename

    @classmethod
    def _build_stamp_image(
        cls,
        stamp_label: str,
    ) -> tuple[BytesIO, float, float]:
        scale = cls.RASTER_SCALE
        font = ImageFont.load_default(size=cls.FONT_SIZE * scale)
        measurement_image = Image.new("RGB", (1, 1), "white")
        measurement_draw = ImageDraw.Draw(measurement_image)
        text_box = measurement_draw.textbbox(
            (0, 0),
            stamp_label,
            font=font,
        )
        horizontal_padding = cls.HORIZONTAL_PADDING * scale
        vertical_padding = cls.VERTICAL_PADDING * scale
        image_width = (
            text_box[2] - text_box[0] + (2 * horizontal_padding)
        )
        image_height = (
            text_box[3] - text_box[1] + (2 * vertical_padding)
        )
        image = Image.new(
            "RGB",
            (image_width, image_height),
            "white",
        )
        draw = ImageDraw.Draw(image)
        draw.text(
            (
                horizontal_padding - text_box[0],
                vertical_padding - text_box[1],
            ),
            stamp_label,
            font=font,
            fill="black",
        )

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output, image_width / scale, image_height / scale
