from __future__ import annotations

from io import BytesIO

from ocr_processor import FileType, ProcessResult, process


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str | None = None):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


def test_process_infers_pdf_type_from_filename():
    file_obj = DummyUploadFile(
        filename="sample.pdf",
        content=b"%PDF-1.4 fake content",
        content_type="application/pdf",
    )

    result = process(file_obj)

    assert isinstance(result, ProcessResult)
    assert result.file_type == FileType.PDF
    assert result.processor_name == "pdf_processor"
    assert result.filename == "sample.pdf"
    assert result.blocks == []
    assert result.meta_info["source"] == "pdf"
    assert result.meta_info["byte_size"] == len(b"%PDF-1.4 fake content")


def test_process_infers_docx_type_from_filename():
    file_obj = DummyUploadFile(
        filename="sample.docx",
        content=b"fake docx content",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    result = process(file_obj)

    assert isinstance(result, ProcessResult)
    assert result.file_type == FileType.DOCX
    assert result.processor_name == "doc_processor"
    assert result.filename == "sample.docx"
    assert result.blocks == []
    assert result.meta_info["source"] == "docx"
    assert result.meta_info["byte_size"] == len(b"fake docx content")


def test_process_allows_explicit_type_override():
    file_obj = DummyUploadFile(
        filename="unknown.bin",
        content=b"fake pdf content",
    )

    result = process(file_obj, "pdf")

    assert result.file_type == FileType.PDF
    assert result.processor_name == "pdf_processor"
