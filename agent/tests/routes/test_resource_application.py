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


@pytest.mark.parametrize("backend", ["openvino", "torch"])
def test_preparation_reuses_model_for_tokenization(monkeypatch, tmp_path, backend):
    """两次真实资源构建共用同一后端模型及其 tokenizer，不为分块再次加载模型。"""
    import sys
    import numpy as np
    from service.document_resources import model, prepare_resources
    from service.document_resources.schemas import InputDocument

    constructed, tokenized, encoded = [], [], []
    class SentenceTransformer:
        def __init__(self, model_id, **kwargs):
            constructed.append((model_id, kwargs))

        def tokenizer(self, text, **kwargs):
            tokenized.append(text)
            return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}

        def get_sentence_embedding_dimension(self):
            return 2

        def encode(self, texts):
            encoded.extend(texts)
            return np.ones((len(texts), 2), dtype=np.float32)

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=SentenceTransformer))
    monkeypatch.setattr(model, "_backend_cache", {})
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "test-model")
    monkeypatch.setenv("EMBEDDING_BACKEND", backend)
    for _ in range(2):
        refs = prepare_resources([InputDocument(filename="合同.html", html="<h1>合同</h1><p>付款期限三十天。</p>")])
        assert [ref.type for ref in refs] == ["documents", "index"]
    options = {"trust_remote_code": True}
    if backend == "openvino":
        options["backend"] = "openvino"
    assert constructed == [("test-model", options)]
    assert tokenized and encoded and tokenized == encoded
