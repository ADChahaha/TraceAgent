"""上传业务入口使用普通文件数据，并在解析前校验整个批次。"""

import importlib
from types import SimpleNamespace

import pytest


def test_invalid_batch_never_parses(monkeypatch):
    app = importlib.import_module("service.document_resources.application")
    monkeypatch.setattr(app.processor, "process", lambda *args: pytest.fail("不能解析部分批次"))
    with pytest.raises(app.processor.UnsupportedFileTypeError):
        app.prepare_uploaded_resources([
            SimpleNamespace(filename="a.pdf", content=b"pdf"),
            SimpleNamespace(filename="bad.txt", content=b"text"),
        ])


def test_upload_preserves_raw_bytes_and_parsed_document(monkeypatch):
    app = importlib.import_module("service.document_resources.application")
    def parse(file):
        assert file.read() == b"pdf"
        return SimpleNamespace(filename=file.filename, html="<p>正文</p>")
    def publish(documents, raw_files):
        assert documents[0].html == "<p>正文</p>"
        assert raw_files == [("a.pdf", b"pdf")]
        return ["published"]
    monkeypatch.setattr(app.processor, "process", parse)
    monkeypatch.setattr(app, "prepare_resources", publish)
    assert app.prepare_uploaded_resources([SimpleNamespace(filename="a.pdf", content=b"pdf")]) == ["published"]
