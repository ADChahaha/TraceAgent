from __future__ import annotations

from io import BytesIO

from ocr_processor import FileType, ProcessResult, process
from ocr_processor.impl import docling_adapter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from docx import Document


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str | None = None):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


def build_pdf_bytes(text: str) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


def build_docx_bytes(paragraphs: list[str]) -> bytes:
    buffer = BytesIO()
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


class FakeDoclingTextItem:
    def __init__(self, text: str):
        self.text = text
        self.prov = []


class FakeDoclingDocument:
    def __init__(self, texts):
        self.texts = texts


class FakeDoclingConversionResult:
    def __init__(self, texts):
        self.document = FakeDoclingDocument(texts)


def test_process_infers_pdf_type_from_filename():
    pdf_bytes = build_pdf_bytes("Hello PDF World")
    file_obj = DummyUploadFile(
        filename="sample.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )

    result = process(file_obj)

    assert isinstance(result, ProcessResult)
    assert result.file_type == FileType.PDF
    assert result.processor_name == "pdf_processor"
    assert result.filename == "sample.pdf"
    assert result.blocks
    assert result.blocks[0].page_no == 1
    assert result.blocks[0].bbox is not None
    assert "Hello" in result.blocks[0].text
    assert result.meta_info["source"] == "pdf"
    assert result.meta_info["byte_size"] == len(pdf_bytes)
    assert result.meta_info["engine"] in {"docling_rapidocr", "pdfplumber_fallback"}


def test_process_infers_docx_type_from_filename(monkeypatch):
    monkeypatch.setattr(
        docling_adapter,
        "convert_with_docling",
        lambda content, filename: FakeDoclingConversionResult([FakeDoclingTextItem("Hello DOCX World")]),
    )

    docx_bytes = build_docx_bytes(["First paragraph", "Second paragraph"])
    file_obj = DummyUploadFile(
        filename="sample.docx",
        content=docx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    result = process(file_obj)

    assert isinstance(result, ProcessResult)
    assert result.file_type == FileType.DOCX
    assert result.processor_name == "doc_processor"
    assert result.filename == "sample.docx"
    assert result.blocks
    assert result.blocks[0].kind == "text"
    assert result.blocks[0].page_no is None
    assert result.blocks[0].bbox is None
    assert result.blocks[0].text == "Hello DOCX World"
    assert result.meta_info["source"] == "docx"
    assert result.meta_info["byte_size"] == len(docx_bytes)


def test_process_allows_explicit_type_override():
    pdf_bytes = build_pdf_bytes("Explicit PDF")
    file_obj = DummyUploadFile(
        filename="unknown.bin",
        content=pdf_bytes,
    )

    result = process(file_obj, "pdf")

    assert result.file_type == FileType.PDF
    assert result.processor_name == "pdf_processor"
    assert result.blocks
