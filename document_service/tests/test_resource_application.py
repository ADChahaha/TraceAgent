"""会话资源入口：桶内 raw 是事实来源，上传即合并，移除即删除并全量重建。"""

import importlib
from types import SimpleNamespace

import pytest

from storage.core.object_store import DirectoryObjectStore


@pytest.fixture
def app():
    return importlib.import_module("document_service.document_resources.application")


@pytest.fixture
def store(tmp_path):
    return DirectoryObjectStore(tmp_path / "storage")


@pytest.fixture
def parsed(app, monkeypatch):
    monkeypatch.setattr(app.processor, "process",
                        lambda file: SimpleNamespace(filename=file.filename, html=f"<p>{file.filename}</p>"))


@pytest.fixture
def published(app, monkeypatch):
    """隔离真实构建：记录 publish_resources 的入参并返回空 refs。"""
    calls = []

    def fake_publish(store, bucket, documents):
        calls.append((store, bucket, list(documents)))
        return []

    monkeypatch.setattr(app, "publish_resources", fake_publish)
    return calls


def upload_file(name, content=b"pdf"):
    return SimpleNamespace(filename=name, content=content)


def raw_ref(bucket, name):
    return {"type": "raw", "location": f"s3://{bucket}/raw/{name}"}


def raw_locations(refs):
    return [ref.location for ref in refs if ref.type == "raw"]


def test_upload_writes_raw_to_session_bucket_and_publishes_parsed_documents(app, store, parsed, published):
    refs = app.prepare_session_resources("s1", [upload_file("a.pdf")], store=store)
    assert store.get_object("res_s1", "raw/a.pdf") == b"pdf"
    assert len(published) == 1
    assert published[0][0] is store
    assert published[0][1] == "res_s1"
    assert [(doc.filename, doc.html) for doc in published[0][2]] == [("a.pdf", "<p>a.pdf</p>")]
    assert raw_locations(refs) == ["s3://res_s1/raw/a.pdf"]


def test_second_upload_reuses_bucket_and_keeps_previous_raws(app, store, parsed, published, tmp_path):
    app.prepare_session_resources("s1", [upload_file("a.pdf")], store=store)
    refs = app.prepare_session_resources("s1", [upload_file("b.pdf")], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/a.pdf", "s3://res_s1/raw/b.pdf"]
    assert store.get_object("res_s1", "raw/a.pdf") == b"pdf"
    assert [doc.filename for doc in published[1][2]] == ["a.pdf", "b.pdf"]
    assert {path.name for path in (tmp_path / "storage").iterdir()} == {"res_s1"}


def test_remove_raw_with_empty_files_deletes_object_and_rebuilds(app, store, parsed, published):
    first = app.prepare_session_resources("s1", [upload_file("a.pdf"), upload_file("b.pdf")], store=store)
    target = next(ref.location for ref in first if ref.type == "raw" and ref.location.endswith("/raw/a.pdf"))
    refs = app.prepare_session_resources("s1", [], [{"type": "raw", "location": target}], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/b.pdf"]
    assert store.get_object("res_s1", "raw/a.pdf") is None
    assert store.get_object("res_s1", "raw/b.pdf") == b"pdf"
    assert [doc.filename for doc in published[1][2]] == ["b.pdf"]


def test_remove_last_raw_clears_published_artifacts(app, store, parsed, published):
    first = app.prepare_session_resources("s1", [upload_file("a.pdf")], store=store)
    target = next(ref.location for ref in first if ref.type == "raw")
    refs = app.prepare_session_resources("s1", [], [{"type": "raw", "location": target}], store=store)
    assert refs == []
    assert len(published) == 1
    assert store.get_object("res_s1", "raw/a.pdf") is None
    assert store.list_objects("res_s1", "raw/") == []
    assert store.list_objects("res_s1", "index/") == []
    assert not (store.root / "res_s1" / "documents.zip").exists()
    assert not (store.root / "res_s1" / "manifest.json").exists()


def test_unknown_remove_target_is_ignored(app, store, parsed, published):
    refs = app.prepare_session_resources("s1", [upload_file("a.pdf")], [raw_ref("res_s1", "ghost.pdf")], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/a.pdf"]


def test_same_name_upload_replaces_raw(app, store, parsed, published):
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"v1")], store=store)
    refs = app.prepare_session_resources("s1", [upload_file("a.pdf", b"v2")], store=store)
    assert store.get_object("res_s1", "raw/a.pdf") == b"v2"
    assert raw_locations(refs) == ["s3://res_s1/raw/a.pdf"]


def test_empty_request_without_removal_is_rejected(app, store, parsed):
    with pytest.raises(ValueError):
        app.prepare_session_resources("s1", [], store=store)


def test_invalid_session_id_is_rejected(app, store, parsed):
    for session_id in ("", "  ", "a/b", "a\\b", ".", ".."):
        with pytest.raises(ValueError):
            app.prepare_session_resources(session_id, [upload_file("a.pdf")], store=store)


def test_remove_raw_must_be_raw_in_session_bucket(app, store, parsed):
    for ref in (
        {"type": "documents", "location": "s3://res_s1/documents.zip"},
        {"type": "raw", "location": "s3://res_other/raw/a.pdf"},
        {"type": "raw", "location": "not-s3"},
    ):
        with pytest.raises(ValueError):
            app.prepare_session_resources("s1", [], [ref], store=store)


def test_rebuild_parses_all_session_raws(app, store, monkeypatch, published):
    seen = []

    def parse(file_obj):
        seen.append((file_obj.filename, file_obj.read()))
        return SimpleNamespace(filename=file_obj.filename, html="<p>x</p>")

    monkeypatch.setattr(app.processor, "process", parse)
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"first")], store=store)
    app.prepare_session_resources("s1", [upload_file("b.pdf", b"second")], store=store)
    assert seen == [("a.pdf", b"first"), ("a.pdf", b"first"), ("b.pdf", b"second")]


def test_upload_rejects_invalid_filename_or_content(app, store, parsed):
    for bad in (SimpleNamespace(filename="", content=b"x"),
                SimpleNamespace(filename="a/b.pdf", content=b"x"),
                SimpleNamespace(filename="a.pdf", content=b"")):
        with pytest.raises(ValueError):
            app.prepare_session_resources("s1", [bad], store=store)
    assert store.list_objects("res_s1", "raw/") == []


def test_invalid_batch_never_parses(app, store, monkeypatch):
    monkeypatch.setattr(app.processor, "process", lambda *args: pytest.fail("不能解析部分批次"))
    with pytest.raises(app.processor.UnsupportedFileTypeError):
        app.prepare_session_resources("s1", [upload_file("bad.txt")], store=store)


def test_failed_parse_leaves_session_bucket_unchanged(app, store, published, monkeypatch):
    """解析失败不写桶：不留孤儿 raw，也不毒化同一会话的后续上传。"""
    def parse(file_obj):
        if file_obj.filename == "bad.pdf":
            raise RuntimeError("corrupt document")
        return SimpleNamespace(filename=file_obj.filename, html="<p>ok</p>")

    monkeypatch.setattr(app.processor, "process", parse)
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"good")], store=store)
    before = store.get_object("res_s1", "documents.zip")

    with pytest.raises(RuntimeError, match="corrupt document"):
        app.prepare_session_resources("s1", [upload_file("bad.pdf", b"broken")], store=store)

    assert store.get_object("res_s1", "raw/bad.pdf") is None
    assert store.get_object("res_s1", "documents.zip") == before
    # 坏文件从未进入桶，后续上传不被毒化。
    refs = app.prepare_session_resources("s1", [upload_file("b.pdf", b"second")], store=store)
    assert [ref.location for ref in refs if ref.type == "raw"] == [
        "s3://res_s1/raw/a.pdf", "s3://res_s1/raw/b.pdf"]


@pytest.mark.parametrize("backend", ["openvino", "torch"])
def test_preparation_reuses_model_for_tokenization(monkeypatch, tmp_path, backend):
    """两次真实资源构建共用同一后端模型及其 tokenizer，不为分块再次加载模型。"""
    import sys
    import numpy as np
    from document_service.document_resources import model, publish_resources
    from document_service.document_resources.schemas import InputDocument

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
        refs = publish_resources(DirectoryObjectStore(tmp_path / "storage"), "res_x",
                                 [InputDocument(filename="合同.html", html="<h1>合同</h1><p>付款期限三十天。</p>")])
        assert [ref.type for ref in refs] == ["documents", "index"]
    options = {"trust_remote_code": True}
    if backend == "openvino":
        options["backend"] = "openvino"
    assert constructed == [("test-model", options)]
    assert tokenized and encoded and tokenized == encoded
