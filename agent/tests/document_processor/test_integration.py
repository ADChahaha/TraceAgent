from __future__ import annotations

from pathlib import Path

from document_processor.processor import process


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "document_processor"


def test_process_handles_real_docx_fixture_via_public_interface():
    fixture_path = FIXTURES_DIR / "实验报告-模板.docx"

    with fixture_path.open("rb") as file_obj:
        result = process(file_obj)

    assert result.file_type == "docx"
    assert result.filename == fixture_path.name
    assert result.warnings == []
    assert result.markdown
    assert result.md_list == [result.markdown]
    assert result.blocks
    assert any(block.text for block in result.blocks)


def test_process_handles_real_pdf_fixture_via_public_interface():
    fixture_path = FIXTURES_DIR / "关于公布2025届校级优秀本科生毕业设计（论文）名单的通知.pdf"

    with fixture_path.open("rb") as file_obj:
        result = process(file_obj)

    assert result.file_type == "pdf"
    assert result.filename == fixture_path.name
    assert result.warnings == []
    assert result.markdown
    assert result.md_list == [result.markdown]
    assert result.blocks
    assert result.meta_info["block_count"] == len(result.blocks)
    assert result.meta_info["page_count"] >= 1
