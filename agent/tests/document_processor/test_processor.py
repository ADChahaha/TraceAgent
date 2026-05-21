from io import BytesIO

import pytest

from service.document_processor.schemas import ProcessResult


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None = None) -> None:
        super().__init__(data)
        self.filename = filename


def test_process_validates_input_then_calls_pdf_pipeline(monkeypatch):
    from service.document_processor import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_convert(source_bytes: bytes, filename: str) -> list[list[dict]]:
        seen_call["source_bytes"] = source_bytes
        seen_call["filename"] = filename
        return [[{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}]]

    monkeypatch.setattr(processor_module, "convert_pdf_bytes_to_content_list", fake_convert)

    file_obj = NamedBytesIO(b"%PDF-1.4", filename="/tmp/sample.PDF")
    result = processor_module.process(file_obj)

    assert result.filename == "sample.PDF"
    assert 'id="p001_b000"' in result.html
    assert "正文" in result.html
    assert result.display_html is not None
    assert "<style>" in result.display_html
    assert 'id="p001_b000"' in result.display_html
    assert "正文" in result.display_html
    assert "<!-- Cluster summary:" not in result.markdown
    assert "<!-- cluster=" not in result.markdown
    assert "正文" in result.markdown
    assert result.md_list == ["正文"]
    assert result.blocks[0]["block_id"] == "p001_b000"
    assert result.blocks[0]["text"] == "正文"
    assert result.semantic_document["sections"][0]["text"] == "正文"
    assert result.semantic_document["blocks"][0]["block_id"] == "p001_b000"
    assert result.meta_info == {"engine": "mineru-pipeline"}
    assert result.warnings == []
    assert seen_call["source_bytes"] == b"%PDF-1.4"
    assert seen_call["filename"] == "sample.PDF"
    assert file_obj.tell() == 0


def test_process_uses_mineru_even_when_pdf_text_layer_is_readable(monkeypatch):
    from service.document_processor import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_convert(source_bytes: bytes, filename: str) -> list[list[dict]]:
        seen_call["source_bytes"] = source_bytes
        seen_call["filename"] = filename
        return [[{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "MinerU正文"}]}}]]

    monkeypatch.setattr(processor_module, "convert_pdf_bytes_to_content_list", fake_convert)

    result = processor_module.process(NamedBytesIO(b"%PDF-1.4", filename="text.pdf"))

    assert result.meta_info == {"engine": "mineru-pipeline"}
    assert result.warnings == []
    assert "MinerU正文" in result.markdown
    assert "MinerU正文" in result.html
    assert result.blocks[0]["block_id"] == "p001_b000"
    assert result.md_list == ["MinerU正文"]
    assert seen_call["source_bytes"] == b"%PDF-1.4"
    assert seen_call["filename"] == "text.pdf"


def test_process_accepts_explicit_pdf_type_without_filename_suffix(monkeypatch):
    from service.document_processor import processor as processor_module

    monkeypatch.setattr(
        processor_module,
        "convert_pdf_bytes_to_content_list",
        lambda source_bytes, filename: [[
            {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}
        ]],
    )

    result = processor_module.process(
        NamedBytesIO(b"%PDF-1.4", filename="upload.bin"),
        file_type=".PDF",
    )

    assert result.filename == "upload.bin"
    assert 'id="p001_b000"' in result.html
    assert result.display_html is not None
    assert 'id="p001_b000"' in result.display_html
    assert "正文" in result.display_html


def test_process_rejects_objects_without_file_like_read_method():
    from service.document_processor import processor as processor_module
    from service.document_processor.processor import InvalidFileObjectError

    with pytest.raises(InvalidFileObjectError, match="file-like"):
        processor_module.process(object(), file_type="pdf")


def test_process_rejects_non_pdf_explicit_type():
    from service.document_processor import processor as processor_module
    from service.document_processor.processor import UnsupportedFileTypeError

    with pytest.raises(UnsupportedFileTypeError, match="docx"):
        processor_module.process(
            NamedBytesIO(b"fake-docx", filename="sample.pdf"),
            file_type="docx",
        )


def test_process_rejects_non_pdf_filename_when_type_is_omitted():
    from service.document_processor import processor as processor_module
    from service.document_processor.processor import UnsupportedFileTypeError

    with pytest.raises(UnsupportedFileTypeError, match="txt"):
        processor_module.process(NamedBytesIO(b"fake", filename="sample.txt"))


def test_process_uses_default_pdf_filename_when_name_is_missing(monkeypatch):
    from service.document_processor import processor as processor_module

    seen_call: dict[str, object] = {}

    def fake_convert(source_bytes, filename):
        seen_call["filename"] = filename
        return [[
            {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}
        ]]

    monkeypatch.setattr(
        processor_module,
        "convert_pdf_bytes_to_content_list",
        fake_convert,
    )

    result = processor_module.process(BytesIO(b"%PDF-1.4"))

    assert result.filename == "document.pdf"
    assert seen_call["filename"] == "document.pdf"
    assert result.display_html is not None
