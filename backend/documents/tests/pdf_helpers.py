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


def pdf_page_contains_image(page) -> bool:
    """Return whether a PDF page or one of its form objects embeds an image."""

    def resources_contain_image(resources) -> bool:
        if not resources:
            return False
        xobjects_reference = resources.get("/XObject")
        if not xobjects_reference:
            return False
        xobjects = xobjects_reference.get_object()
        for reference in xobjects.values():
            xobject = reference.get_object()
            subtype = xobject.get("/Subtype")
            if subtype == "/Image":
                return True
            if subtype == "/Form" and resources_contain_image(
                xobject.get("/Resources")
            ):
                return True
        return False

    return resources_contain_image(page.get("/Resources"))
