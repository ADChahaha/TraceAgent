from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from ocr_processor import FileType, process

_DOCX_SAMPLE_PATH = Path("示例 DOCX 文件")
_PDF_SAMPLE_PATH = Path("示例 PDF 文件")


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str | None = None):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


def _load_upload_file(path: Path, content_type: str) -> DummyUploadFile:
    if not path.exists():
        pytest.skip(f"Sample document was not found: {path}")
    return DummyUploadFile(
        filename=path.name,
        content=path.read_bytes(),
        content_type=content_type,
    )


def test_sample_docx_exports_structured_markdown():
    file_obj = _load_upload_file(
        _DOCX_SAMPLE_PATH,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    result = process(file_obj)

    assert result.file_type == FileType.DOCX
    assert len(result.blocks) >= 10
    assert len(result.md_list) == len(result.blocks)
    assert len(result.markdown) >= 100
    assert "杭州电子科技大学" in result.markdown
    assert "实验报告" in result.markdown
    assert "| 题 目 |  |" in result.markdown
    assert "22\n\n2\n\n2" not in result.markdown
    assert any(item.startswith("# ") for item in result.md_list)
    assert result.meta_info["fallback_used"] is True


def test_sample_pdf_renders_markdown_with_table_content():
    file_obj = _load_upload_file(_PDF_SAMPLE_PATH, "application/pdf")

    result = process(file_obj)

    assert result.file_type == FileType.PDF
    assert len(result.blocks) >= 5
    assert len(result.md_list) == len(result.blocks)
    assert len(result.markdown) >= 1000
    assert "优秀指导教师名单" in result.markdown
    assert "|   序号 | 学院" in result.markdown
    assert result.meta_info["has_table"] is True
