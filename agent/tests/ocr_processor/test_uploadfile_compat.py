from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from docx import Document
from starlette.datastructures import UploadFile as StarletteUploadFile

import ocr_processor
from ocr_processor import FileType, process
from ocr_processor.impl.doc import docling_adapter as doc_docling_adapter


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


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    buffer = BytesIO()
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


def test_process_accepts_starlette_upload_file(monkeypatch):
    monkeypatch.setattr(
        doc_docling_adapter,
        "convert_with_docling",
        lambda content, filename: FakeDoclingConversionResult([FakeDoclingTextItem("Hello UploadFile")]),
    )

    upload_file = StarletteUploadFile(
        file=BytesIO(_build_docx_bytes(["First paragraph"])),
        filename="upload.docx",
    )

    result = process(upload_file)

    assert result.file_type == FileType.DOCX
    assert result.filename == "upload.docx"
    assert result.md_list == ["Hello UploadFile"]
    assert result.markdown == "Hello UploadFile"


def test_root_package_does_not_export_internal_markdown_helper():
    assert not hasattr(ocr_processor, "build_markdown_from_blocks")
