"""会话资源入口：桶内 raw 是事实来源，上传增量构建，纯删除复用既有文档和向量。"""

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

    def fake_publish(store, bucket, documents, **kwargs):
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
    assert [doc.filename for doc in published[1][2]] == ["b.pdf"]
    assert {path.name for path in (tmp_path / "storage").iterdir()} == {"res_s1"}


def test_remove_raw_with_empty_files_deletes_object_and_prunes(app, store, parsed, published, monkeypatch):
    pruned = []
    monkeypatch.setattr(app, "remove_published_documents", lambda store, bucket, names: pruned.append((bucket, names)) or [])
    first = app.prepare_session_resources("s1", [upload_file("a.pdf"), upload_file("b.pdf")], store=store)
    target = next(ref.location for ref in first if ref.type == "raw" and ref.location.endswith("/raw/a.pdf"))
    refs = app.prepare_session_resources("s1", [], [{"type": "raw", "location": target}], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/b.pdf"]
    assert store.get_object("res_s1", "raw/a.pdf") is None
    assert store.get_object("res_s1", "raw/b.pdf") == b"pdf"
    assert len(published) == 1
    assert pruned == [("res_s1", {"a.pdf"})]


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


def test_upload_parses_only_new_files(app, store, monkeypatch, published):
    seen = []

    def parse(file_obj):
        seen.append((file_obj.filename, file_obj.read()))
        return SimpleNamespace(filename=file_obj.filename, html="<p>x</p>")

    monkeypatch.setattr(app.processor, "process", parse)
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"first")], store=store)
    app.prepare_session_resources("s1", [upload_file("b.pdf", b"second")], store=store)
    assert seen == [("a.pdf", b"first"), ("b.pdf", b"second")]


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


@pytest.fixture
def indexed(app, store, parsed, monkeypatch, tmp_path):
    """生成真实归档与索引，随后禁止解析、模型加载及 raw 下载。"""
    import numpy as np
    from document_service.document_resources import model
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "torch")
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: SimpleNamespace(
        tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
        encode=lambda texts: np.arange(1, len(texts) * 2 + 1, dtype=np.float32).reshape(-1, 2)))
    app.prepare_session_resources("s1", [upload_file(name) for name in ("a.pdf", "b.pdf", "c.pdf")], store=store)
    monkeypatch.setattr(app.processor, "process", lambda *args: pytest.fail("删除不能重新解析"))
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: pytest.fail("删除不能加载 embedding 模型"))
    original_get = store.get_object
    def get(bucket, key):
        assert not key.startswith("raw/"), "删除不能下载原文件"
        return original_get(bucket, key)
    monkeypatch.setattr(store, "get_object", get)
    return store


@pytest.mark.parametrize("legacy", [False, True])
def test_remove_reuses_vectors_and_preserves_paths_across_repeated_deletes(app, indexed, legacy):
    import io
    import json
    import zipfile
    import numpy as np
    bucket = "res_s1"
    manifest = json.loads(indexed.get_object(bucket, "manifest.json"))
    if legacy:
        manifest.pop("document_roots", None)
        indexed.put_object(bucket, "manifest.json", json.dumps(manifest).encode())
    before = json.loads(indexed.get_object(bucket, "index/index.json"))
    vectors = np.load(io.BytesIO(indexed.get_object(bucket, "index/vectors.npy")))
    with zipfile.ZipFile(io.BytesIO(indexed.get_object(bucket, "documents.zip"))) as archive:
        original_files = {key: archive.read(key) for key in archive.namelist()}
    for name, remaining in [("a.pdf", ["b.pdf", "c.pdf"]), ("b.pdf", ["c.pdf"])]:
        refs = app.prepare_session_resources("s1", [], [raw_ref(bucket, name)], store=indexed)
        assert raw_locations(refs) == [f"s3://{bucket}/raw/{file}" for file in remaining]
        assert sorted(indexed.list_objects(bucket, "raw/")) == [f"raw/{file}" for file in remaining]
        meta = json.loads(indexed.get_object(bucket, "index/index.json"))
        keep = [i for i, chunk in enumerate(before["chunks"]) if chunk["document"].split("-", 1)[1] + ".pdf" in remaining]
        assert meta["chunks"] == [before["chunks"][i] for i in keep]
        np.testing.assert_array_equal(np.load(io.BytesIO(indexed.get_object(bucket, "index/vectors.npy"))), vectors[keep])
        with zipfile.ZipFile(io.BytesIO(indexed.get_object(bucket, "documents.zip"))) as archive:
            assert {key: archive.read(key) for key in archive.namelist()} == {
                key: value for key, value in original_files.items() if key.split("/")[1].split("-", 1)[1] + ".pdf" in remaining}
        assert json.loads(indexed.get_object(bucket, "manifest.json"))["documents"] == remaining
    app.prepare_session_resources("s1", [], [raw_ref(bucket, "c.pdf")], store=indexed)
    assert indexed.list_objects(bucket, "") == []


def test_remove_invalid_index_leaves_raw_and_published_objects_unchanged(app, indexed):
    indexed.put_object("res_s1", "index/vectors.npy", b"broken")
    before = {key: indexed.get_object("res_s1", key) for key in indexed.list_objects("res_s1", "") if not key.startswith("raw/")}
    with pytest.raises(ValueError):
        app.prepare_session_resources("s1", [], [raw_ref("res_s1", "a.pdf")], store=indexed)
    assert sorted(indexed.list_objects("res_s1", "raw/")) == ["raw/a.pdf", "raw/b.pdf", "raw/c.pdf"]
    assert before == {key: indexed.get_object("res_s1", key) for key in before}


def test_remove_multiple_and_unknown_targets_without_rebuilding(app, indexed):
    refs = app.prepare_session_resources("s1", [], [raw_ref("res_s1", name) for name in ("a.pdf", "c.pdf", "ghost.pdf")], store=indexed)
    assert raw_locations(refs) == ["s3://res_s1/raw/b.pdf"]
    before = {key: indexed.get_object("res_s1", key) for key in indexed.list_objects("res_s1", "") if not key.startswith("raw/")}
    assert app.prepare_session_resources("s1", [], [raw_ref("res_s1", "a.pdf")], store=indexed) == refs
    assert before == {key: indexed.get_object("res_s1", key) for key in before}


def test_remove_preserves_empty_document_without_vectors(app, store, monkeypatch, tmp_path):
    from document_service.document_resources import model
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "torch")
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: SimpleNamespace(tokenize=lambda text: []))
    monkeypatch.setattr(app.processor, "process", lambda file: SimpleNamespace(filename=file.filename, html="<div></div>"))
    app.prepare_session_resources("s1", [upload_file("a.pdf"), upload_file("b.pdf")], store=store)
    refs = app.prepare_session_resources("s1", [], [raw_ref("res_s1", "a.pdf")], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/b.pdf"]


@pytest.mark.parametrize("legacy", [False, True])
def test_upload_only_encodes_new_documents_and_preserves_existing_artifacts(app, store, monkeypatch, tmp_path, legacy):
    import io
    import json
    import zipfile
    import numpy as np
    from document_service.document_resources import model
    parsed_names, encoded = [], []
    def parse(file):
        parsed_names.append(file.filename)
        return SimpleNamespace(filename=file.filename, html=f"<p>{file.read().decode()}</p>")
    def encode(texts):
        encoded.extend(texts)
        return np.array([[len(text), 1] for text in texts], dtype=np.float32)
    monkeypatch.setattr(app.processor, "process", parse)
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: SimpleNamespace(
        tokenize=lambda text: [(i, i + 1) for i in range(len(text))], encode=encode))
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    bucket = "res_s1"
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"old a"), upload_file("b.pdf", b"old b")], store=store)
    manifest = json.loads(store.get_object(bucket, "manifest.json"))
    if legacy:
        manifest.pop("document_roots")
        store.put_object(bucket, "manifest.json", json.dumps(manifest).encode())
    before = json.loads(store.get_object(bucket, "index/index.json"))
    vectors = np.load(io.BytesIO(store.get_object(bucket, "index/vectors.npy")))
    with zipfile.ZipFile(io.BytesIO(store.get_object(bucket, "documents.zip"))) as z:
        files = {name: z.read(name) for name in z.namelist()}
    original_get = store.get_object
    def get(bucket, key):
        assert not key.startswith("raw/"), "补传不能下载旧原文件"
        return original_get(bucket, key)
    monkeypatch.setattr(store, "get_object", get)
    parsed_names.clear(); encoded.clear()
    app.prepare_session_resources("s1", [upload_file("c.pdf", b"new c")], store=store)
    assert parsed_names == ["c.pdf"] and encoded == ["new c"]
    after = json.loads(store.get_object(bucket, "index/index.json"))
    assert after["chunks"][:2] == before["chunks"]
    np.testing.assert_array_equal(np.load(io.BytesIO(store.get_object(bucket, "index/vectors.npy")))[:2], vectors)
    with zipfile.ZipFile(io.BytesIO(store.get_object(bucket, "documents.zip"))) as z:
        assert all(z.read(name) == content for name, content in files.items())
    parsed_names.clear(); encoded.clear()
    app.prepare_session_resources("s1", [upload_file("a.pdf", b"updated a"), upload_file("d.pdf", b"new d")],
                                  [raw_ref(bucket, "c.pdf")], store=store)
    assert parsed_names == ["a.pdf", "d.pdf"] and encoded == ["updated a", "new d"]
    final = json.loads(store.get_object(bucket, "index/index.json"))
    assert final["chunks"][0] == before["chunks"][1]
    assert {chunk["text"] for chunk in final["chunks"]} == {"old b", "updated a", "new d"}
    assert len({chunk["chunk_id"] for chunk in final["chunks"]}) == 3
    assert sorted(store.list_objects(bucket, "raw/")) == ["raw/a.pdf", "raw/b.pdf", "raw/d.pdf"]


def test_failed_incremental_embedding_keeps_all_objects_unchanged(app, store, parsed, monkeypatch, tmp_path):
    import numpy as np
    from document_service.document_resources import model
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: SimpleNamespace(
        tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
        encode=lambda texts: np.ones((len(texts), 2), dtype=np.float32)))
    app.prepare_session_resources("s1", [upload_file("a.pdf")], store=store)
    before = {key: store.get_object("res_s1", key) for key in store.list_objects("res_s1", "")}
    def fail(**kwargs):
        raise RuntimeError("embedding failed")
    monkeypatch.setattr(model, "get_embedder", fail)
    with pytest.raises(RuntimeError, match="embedding failed"):
        app.prepare_session_resources("s1", [upload_file("b.pdf")], store=store)
    assert before == {key: store.get_object("res_s1", key) for key in store.list_objects("res_s1", "")}


@pytest.mark.parametrize("first_empty", [False, True])
def test_incremental_upload_handles_documents_without_chunks(app, store, monkeypatch, tmp_path, first_empty):
    import io
    import json
    import numpy as np
    from document_service.document_resources import model
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setattr(app.processor, "process", lambda file: SimpleNamespace(
        filename=file.filename, html="<div></div>" if file.filename == "empty.pdf" else "<p>正文</p>"))
    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: SimpleNamespace(
        tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
        encode=lambda texts: np.ones((len(texts), 2), dtype=np.float32)))
    names = ["empty.pdf", "text.pdf"] if first_empty else ["text.pdf", "empty.pdf"]
    for name in names:
        app.prepare_session_resources("s1", [upload_file(name)], store=store)
    meta = json.loads(store.get_object("res_s1", "index/index.json"))
    assert len(meta["chunks"]) == 1 and meta["dimension"] == 2
    assert np.load(io.BytesIO(store.get_object("res_s1", "index/vectors.npy"))).shape == (1, 2)
    refs = app.prepare_session_resources("s1", [], [raw_ref("res_s1", "text.pdf")], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/empty.pdf"]
