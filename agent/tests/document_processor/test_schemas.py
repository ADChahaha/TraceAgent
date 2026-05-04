from dataclasses import asdict, fields, is_dataclass

from service.document_processor.schemas import ProcessResult


def test_process_result_exposes_extraction_and_display_html():
    result = ProcessResult(filename="sample.pdf", html="<html>正文</html>")

    assert is_dataclass(ProcessResult)
    assert [field.name for field in fields(ProcessResult)] == [
        "filename",
        "html",
        "display_html",
        "markdown",
        "md_list",
        "blocks",
        "meta_info",
        "warnings",
    ]
    assert result.filename == "sample.pdf"
    assert result.html == "<html>正文</html>"
    assert result.display_html is None
    assert result.markdown == ""
    assert result.md_list == []
    assert result.blocks == []
    assert result.meta_info == {}
    assert result.warnings == []


def test_process_result_serializes_as_plain_dataclass_data():
    result = ProcessResult(filename="sample.pdf", html="<article>正文</article>")

    assert asdict(result) == {
        "filename": "sample.pdf",
        "html": "<article>正文</article>",
        "display_html": None,
        "markdown": "",
        "md_list": [],
        "blocks": [],
        "meta_info": {},
        "warnings": [],
    }
