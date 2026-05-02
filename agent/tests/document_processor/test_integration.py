from __future__ import annotations

from pathlib import Path

from service.document_processor.processor import process


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "document_processor"


def test_process_handles_real_pdf_fixture_via_public_interface(monkeypatch):
    from service.document_processor import processor as processor_module

    fixture_path = FIXTURES_DIR / "关于公布2025届校级优秀本科生毕业设计（论文）名单的通知.pdf"
    seen_call: dict[str, object] = {}

    def fake_convert(source_bytes: bytes, filename: str) -> object:
        seen_call["source_prefix"] = source_bytes[:4]
        seen_call["filename"] = filename
        return object()

    monkeypatch.setattr(processor_module, "convert_to_docling_document", fake_convert)
    monkeypatch.setattr(
        processor_module,
        "export_html",
        lambda document: "<html><body><p>真实 PDF fixture</p></body></html>",
    )

    with fixture_path.open("rb") as file_obj:
        result = process(file_obj)

    assert result.filename == fixture_path.name
    assert result.html == '<p id="dp-p-1">真实 PDF fixture</p>'
    assert seen_call["source_prefix"] == b"%PDF"
    assert seen_call["filename"] == fixture_path.name
