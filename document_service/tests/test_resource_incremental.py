"""会话资源增量构建、删除复用向量与坏索引拒绝保护测试。"""

import importlib
import io
import json
import zipfile
from types import SimpleNamespace

import numpy as np
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
    monkeypatch.setattr(
        app.processor,
        "process",
        lambda file: SimpleNamespace(filename=file.filename, html=f"<p>{file.filename}</p>"),
    )


def upload_file(name, content=b"pdf"):
    return SimpleNamespace(filename=name, content=content)


def raw_ref(bucket, name):
    return {"type": "raw", "location": f"s3://{bucket}/raw/{name}"}


def raw_locations(refs):
    return [ref.location for ref in refs if ref.type == "raw"]


@pytest.fixture
def indexed(app, store, parsed, monkeypatch, tmp_path):
    """生成真实归档与索引，随后禁止解析、模型加载及 raw 下载。"""
    from document_service.document_resources import model

    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "torch")
    monkeypatch.setattr(
        model,
        "get_embedder",
        lambda **kwargs: SimpleNamespace(
            tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
            encode=lambda texts: np.arange(1, len(texts) * 2 + 1, dtype=np.float32).reshape(-1, 2),
        ),
    )
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
                key: value
                for key, value in original_files.items()
                if key.split("/")[1].split("-", 1)[1] + ".pdf" in remaining
            }
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
    refs = app.prepare_session_resources(
        "s1", [], [raw_ref("res_s1", name) for name in ("a.pdf", "c.pdf", "ghost.pdf")], store=indexed
    )
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
    from document_service.document_resources import model

    parsed_names, encoded = [], []

    def parse(file):
        parsed_names.append(file.filename)
        return SimpleNamespace(filename=file.filename, html=f"<p>{file.read().decode()}</p>")

    def encode(texts):
        encoded.extend(texts)
        return np.array([[len(text), 1] for text in texts], dtype=np.float32)

    monkeypatch.setattr(app.processor, "process", parse)
    monkeypatch.setattr(
        model,
        "get_embedder",
        lambda **kwargs: SimpleNamespace(tokenize=lambda text: [(i, i + 1) for i in range(len(text))], encode=encode),
    )
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
    parsed_names.clear()
    encoded.clear()
    app.prepare_session_resources("s1", [upload_file("c.pdf", b"new c")], store=store)
    assert parsed_names == ["c.pdf"] and encoded == ["new c"]
    after = json.loads(store.get_object(bucket, "index/index.json"))
    assert after["chunks"][:2] == before["chunks"]
    np.testing.assert_array_equal(np.load(io.BytesIO(store.get_object(bucket, "index/vectors.npy")))[:2], vectors)
    with zipfile.ZipFile(io.BytesIO(store.get_object(bucket, "documents.zip"))) as z:
        assert all(z.read(name) == content for name, content in files.items())
    parsed_names.clear()
    encoded.clear()
    app.prepare_session_resources(
        "s1", [upload_file("a.pdf", b"updated a"), upload_file("d.pdf", b"new d")], [raw_ref(bucket, "c.pdf")], store=store
    )
    assert parsed_names == ["a.pdf", "d.pdf"] and encoded == ["updated a", "new d"]
    final = json.loads(store.get_object(bucket, "index/index.json"))
    assert final["chunks"][0] == before["chunks"][1]
    assert {chunk["text"] for chunk in final["chunks"]} == {"old b", "updated a", "new d"}
    assert len({chunk["chunk_id"] for chunk in final["chunks"]}) == 3
    assert sorted(store.list_objects(bucket, "raw/")) == ["raw/a.pdf", "raw/b.pdf", "raw/d.pdf"]


def test_failed_incremental_embedding_keeps_all_objects_unchanged(app, store, parsed, monkeypatch, tmp_path):
    from document_service.document_resources import model

    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setattr(
        model,
        "get_embedder",
        lambda **kwargs: SimpleNamespace(
            tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
            encode=lambda texts: np.ones((len(texts), 2), dtype=np.float32),
        ),
    )
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
    from document_service.document_resources import model

    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))
    monkeypatch.setattr(
        app.processor,
        "process",
        lambda file: SimpleNamespace(
            filename=file.filename, html="<div></div>" if file.filename == "empty.pdf" else "<p>正文</p>"
        ),
    )
    monkeypatch.setattr(
        model,
        "get_embedder",
        lambda **kwargs: SimpleNamespace(
            tokenize=lambda text: [(i, i + 1) for i in range(len(text))],
            encode=lambda texts: np.ones((len(texts), 2), dtype=np.float32),
        ),
    )
    names = ["empty.pdf", "text.pdf"] if first_empty else ["text.pdf", "empty.pdf"]
    for name in names:
        app.prepare_session_resources("s1", [upload_file(name)], store=store)
    meta = json.loads(store.get_object("res_s1", "index/index.json"))
    assert len(meta["chunks"]) == 1 and meta["dimension"] == 2
    assert np.load(io.BytesIO(store.get_object("res_s1", "index/vectors.npy"))).shape == (1, 2)
    refs = app.prepare_session_resources("s1", [], [raw_ref("res_s1", "text.pdf")], store=store)
    assert raw_locations(refs) == ["s3://res_s1/raw/empty.pdf"]
