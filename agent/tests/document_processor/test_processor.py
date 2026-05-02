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

    def fake_convert(source_bytes: bytes, filename: str) -> object:
        seen_call["source_bytes"] = source_bytes
        seen_call["filename"] = filename
        return object()

    def fake_export(document: object) -> str:
        seen_call["document"] = document
        return (
            "<html><head><style>.x{}</style></head><body>"
            '<p class="ignored">正文</p>'
            "</body></html>"
        )

    monkeypatch.setattr(processor_module, "convert_to_docling_document", fake_convert)
    monkeypatch.setattr(processor_module, "export_html", fake_export)

    file_obj = NamedBytesIO(b"%PDF-1.4", filename="/tmp/sample.PDF")
    result = processor_module.process(file_obj)

    assert result == ProcessResult(
        filename="sample.PDF",
        html='<p id="dp-p-1">正文</p>',
        display_html=result.display_html,
    )
    assert result.display_html is not None
    assert "<style>" in result.display_html
    assert 'id="dp-p-1"' in result.display_html
    assert 'class="ignored"' in result.display_html
    assert "正文" in result.display_html
    assert "<style>" not in result.html
    assert seen_call["source_bytes"] == b"%PDF-1.4"
    assert seen_call["filename"] == "sample.PDF"
    assert file_obj.tell() == 0


def test_process_accepts_explicit_pdf_type_without_filename_suffix(monkeypatch):
    from service.document_processor import processor as processor_module

    monkeypatch.setattr(
        processor_module,
        "convert_to_docling_document",
        lambda source_bytes, filename: object(),
    )
    monkeypatch.setattr(
        processor_module,
        "export_html",
        lambda document: "<html><body><p>正文</p></body></html>",
    )

    result = processor_module.process(
        NamedBytesIO(b"%PDF-1.4", filename="upload.bin"),
        file_type=".PDF",
    )

    assert result.filename == "upload.bin"
    assert result.html == '<p id="dp-p-1">正文</p>'
    assert result.display_html is not None
    assert 'id="dp-p-1"' in result.display_html
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
    monkeypatch.setattr(
        processor_module,
        "convert_to_docling_document",
        lambda source_bytes, filename: seen_call.setdefault("filename", filename)
        or object(),
    )
    monkeypatch.setattr(
        processor_module,
        "export_html",
        lambda document: "<html>正文</html>",
    )

    result = processor_module.process(BytesIO(b"%PDF-1.4"))

    assert result.filename == "document.pdf"
    assert seen_call["filename"] == "document.pdf"
    assert result.display_html is not None


def test_process_merges_continued_tables_before_cleaning(monkeypatch):
    from service.document_processor import processor as processor_module

    monkeypatch.setattr(
        processor_module,
        "convert_to_docling_document",
        lambda source_bytes, filename: object(),
    )
    monkeypatch.setattr(
        processor_module,
        "export_html",
        lambda document: """
        <table>
          <tr><th>楼栋</th><th>房间</th><th>平均分</th><th>模范/文明</th></tr>
          <tr><td>18栋</td><td>219</td><td>87.33</td><td></td></tr>
        </table>
        <table>
          <tr><th>18栋</th><th>220</th><th>85.67</th><td></td></tr>
          <tr><td>18栋</td><td>221</td><td>84.92</td><td></td></tr>
        </table>
        """,
    )

    result = processor_module.process(
        NamedBytesIO(b"%PDF-1.4", filename="sample.pdf")
    )

    assert result.html.count("<table") == 1
    assert "<td>220</td>" in result.html
    assert "<td>221</td>" in result.html
    assert result.display_html is not None
    assert result.display_html.count("<table") == 1
