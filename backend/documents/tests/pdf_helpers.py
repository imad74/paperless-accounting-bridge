from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf_upload(
    *,
    name="scan.pdf",
    page_count=1,
    marker="Document de test",
):
    output = BytesIO()
    pdf_canvas = canvas.Canvas(
        output,
        pagesize=A4,
        invariant=1,
    )
    for page_number in range(1, page_count + 1):
        pdf_canvas.drawString(
            36,
            A4[1] - 36,
            f"{marker} - page {page_number}",
        )
        pdf_canvas.showPage()
    pdf_canvas.save()
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type="application/pdf",
    )
