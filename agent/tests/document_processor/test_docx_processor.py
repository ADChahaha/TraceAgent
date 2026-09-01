from __future__ import annotations

from io import BytesIO

from docx import Document


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None = None) -> None:
        super().__init__(data)
        self.filename = filename


def build_docx_bytes(*, with_headings: bool) -> bytes:
    document = Document()
    if with_headings:
        document.add_heading("Overview", level=1)
        document.add_paragraph("Alpha paragraph.")
        document.add_heading("Details", level=2)
        document.add_paragraph("Beta paragraph.")
    else:
        document.add_paragraph("Plain first paragraph.")
        document.add_paragraph("Plain second paragraph.")

    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Term"
    table.cell(0, 1).text = "Notice"
    table.cell(1, 0).text = "Termination"
    table.cell(1, 1).text = "30 days"

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_process_docx_builds_sections_from_word_heading_styles():
    from service.document_processor import processor

    file_obj = NamedBytesIO(build_docx_bytes(with_headings=True), filename="/tmp/sample.DOCX")

    result = processor.process(file_obj)

    assert result.filename == "sample.DOCX"
    assert file_obj.tell() == 0
    assert "<html" in result.html
    assert "docx_b005_tr_002" in result.html
    assert 'id="docx_b001_section"' in result.html
    assert '<h1 id="docx_b001"' in result.html
    assert '<h2 id="docx_b003"' in result.html
    assert '<table id="docx_b005"' in result.html
    assert "<html" in result.html
    assert "Overview" in result.html
    assert "Alpha paragraph." in result.html


def test_process_docx_without_heading_styles_keeps_flat_original_order():
    from service.document_processor import processor

    file_obj = NamedBytesIO(build_docx_bytes(with_headings=False), filename="flat.docx")

    result = processor.process(file_obj)

    assert '<section id=' not in result.html
    assert "<h1" not in result.html
    assert "Plain first paragraph." in result.html
    assert "Plain second paragraph." in result.html
    assert "Termination" in result.html
    assert "30 days" in result.html
