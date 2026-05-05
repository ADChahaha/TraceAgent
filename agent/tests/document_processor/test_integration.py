from __future__ import annotations

from service.document_processor.processor import process


MINIMAL_PDF_BYTES = b"%PDF-1.4\n% TraceAgent synthetic PDF fixture\n%%EOF\n"


def test_process_handles_pdf_file_path_via_public_interface(monkeypatch, tmp_path):
    from service.document_processor import processor as processor_module

    fixture_path = tmp_path / "sample_notice.pdf"
    fixture_path.write_bytes(MINIMAL_PDF_BYTES)
    seen_call: dict[str, object] = {}

    def fake_convert(source_bytes: bytes, filename: str) -> list[list[dict]]:
        seen_call["source_prefix"] = source_bytes[:4]
        seen_call["filename"] = filename
        return [[
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "合成 PDF fixture"}
                    ]
                },
            }
        ]]

    monkeypatch.setattr(processor_module, "convert_pdf_bytes_to_content_list", fake_convert)

    with fixture_path.open("rb") as file_obj:
        result = process(file_obj)

    assert result.filename == fixture_path.name
    assert 'id="p001_b000"' in result.html
    assert "合成 PDF fixture" in result.html
    assert seen_call["source_prefix"] == b"%PDF"
    assert seen_call["filename"] == fixture_path.name
