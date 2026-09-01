from dataclasses import asdict, fields, is_dataclass

from service.document_processor.schemas import ProcessResult


def test_process_result_exposes_filename_and_html():
    result = ProcessResult(filename="sample.pdf", html="<html>正文</html>")

    assert is_dataclass(ProcessResult)
    assert [field.name for field in fields(ProcessResult)] == [
        "filename",
        "html",
    ]
    assert result.filename == "sample.pdf"
    assert result.html == "<html>正文</html>"


def test_process_result_serializes_as_plain_dataclass_data():
    result = ProcessResult(filename="sample.pdf", html="<article>正文</article>")

    assert asdict(result) == {
        "filename": "sample.pdf",
        "html": "<article>正文</article>",
    }
