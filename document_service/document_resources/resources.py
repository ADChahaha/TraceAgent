"""HTML → 临时文档树与 embedding 索引 → 校验产物 → 逐对象上传到指定桶。

publish_resources 调用 materialize_tree、build_index，先在本机临时目录构建并校验，
然后把 documents 文件树打成单个 documents.zip，index/manifest 独立写入调用方指定的
ObjectStore 桶，最后返回 documents/index 资源定位数组 [{type, location}]。桶内
raw/ 对象的写入与删除由会话层（application）负责，本模块只覆盖构建产物。
读取端把 documents.zip 解到内存虚拟文件系统，索引仍从独立对象读取。

remove_published_documents 在删除时读取既有归档与索引，按文件到目录映射剔除
目标文档及对应向量行，校验后重新发布；剩余路径、分块和向量原样保留。
已发布资源由 Agent 工具从 ObjectStore 读取，本模块不提供消费端加载接口。
构建或校验失败不开始上传；上传失败可能留下远端部分对象，不返回资源定位。
成功或失败都会清理本地临时目录；当前没有远端回滚或原子发布机制。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import uuid
import zipfile
from tempfile import TemporaryDirectory
from dataclasses import asdict
from pathlib import Path

import numpy as np

from traceagent_shared.object_store import ObjectStore, ResourceRef
from document_service.document_resources import model
from document_service.document_resources.documents import materialize_tree, order_key
from document_service.document_resources.schemas import InputDocument
from document_service.document_resources.index import Chunk, build_index


def resources_root() -> Path:
    return Path(os.getenv("DOCUMENT_RESOURCES_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "resources"))).resolve()


def publish_resources(
    store: ObjectStore,
    bucket: str,
    documents: list[InputDocument],
    *,
    incremental: bool = False,
    removed: set[str] | frozenset[str] = frozenset(),
) -> list[ResourceRef]:
    """在给定桶内构建并发布文档树归档与索引，返回 documents/index 资源定位数组。"""
    if not documents or any(not doc.filename.strip() or not doc.html.strip() for doc in documents):
        raise ValueError("documents require non-empty filename and html")
    parent = resources_root()
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".building-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        previous = _load_published(store, bucket, temporary) if incremental else None
        roots = _document_roots(previous, temporary) if previous else {}
        model_id = previous["embedding_model"] if previous else os.getenv("EMBEDDING_MODEL", model.DEFAULT_EMBEDDING_MODEL)
        backend = previous["embedding_backend"] if previous else os.getenv("EMBEDDING_BACKEND", "openvino")
        chunk_size = previous["chunk_size"] if previous else int(os.getenv("EMBEDDING_CHUNK_SIZE", "256"))
        overlap = previous["overlap"] if previous else int(os.getenv("EMBEDDING_CHUNK_OVERLAP", "32"))
        replaced = removed | {doc.filename for doc in documents}
        removed_roots = {root for name, root in roots.items() if name in replaced}
        old_meta = json.loads((temporary / "index/index.json").read_text()) if previous else None
        old_vectors = np.load(temporary / "index/vectors.npy", allow_pickle=False) if previous else None
        for root in removed_roots:
            target = (temporary / "documents" / root).resolve()
            if target.parent != temporary / "documents":
                raise ValueError("invalid document root")
            if target.exists():
                shutil.rmtree(target)
        next_number = max((order_key(root) for root in roots.values()), default=0) + 1
        roots = {name: root for name, root in roots.items() if name not in replaced}
        document = temporary / "documents"
        document.mkdir(exist_ok=True)
        # 新目录先独立生成，再编号，避免覆盖已有路径或改变历史引用。
        staging = materialize_tree(documents, temporary / "new-documents")
        new_roots = []
        for source, entry in zip(documents, sorted(staging.iterdir(), key=lambda item: order_key(item.name))):
            root = f"{next_number:03d}-" + entry.name.split("-", 1)[1]
            next_number += 1
            entry.rename(document / root)
            roots[source.filename] = root
            new_roots.append(root)
        staging.rmdir()
        embedder = model.get_embedder(model_id=model_id, backend=backend)
        index = build_index(
            _document_streams(document, roots=set(new_roots)), embedder=embedder,
            model_id=model_id, tokenize=embedder.tokenize,
            chunk_size=chunk_size, overlap=overlap,
        )
        chunks = [asdict(chunk) for chunk in index.chunks]
        vectors = index.vectors
        dimension = index.dimension
        if old_meta is not None:
            keep = [i for i, chunk in enumerate(old_meta["chunks"]) if chunk["document"] not in removed_roots]
            if keep:
                if chunks and dimension != old_meta["dimension"]:
                    raise ValueError("embedding dimension changed")
                dimension = old_meta["dimension"]
                vectors = np.concatenate([old_vectors[keep], vectors]) if chunks else old_vectors[keep]
                chunks = [old_meta["chunks"][i] for i in keep] + chunks
        index_dir = temporary / "index"
        index_dir.mkdir(exist_ok=True)
        _write_json(index_dir / "index.json", {
            "model_id": model_id, "dimension": dimension,
            "chunks": chunks,
        })
        np.save(index_dir / "vectors.npy", vectors, allow_pickle=False)
        _write_json(temporary / "manifest.json", {
            "version": 1, "embedding_model": model_id, "embedding_backend": backend,
            "chunk_size": chunk_size, "overlap": overlap,
            "documents": list(roots),
            "document_roots": roots,
        })
        _validate_prepared(temporary)
        _publish_to_store(store, bucket, temporary)
    except BaseException:
        if temporary.resolve().parent == parent and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if temporary.resolve().parent == parent and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)
    return _resource_refs(bucket)


def _publish_to_store(
    store: ObjectStore,
    bucket: str,
    temporary: Path,
) -> None:
    """把文档树打成单个 zip，索引与清单独立上传到指定桶；raw 对象由会话层管理。"""
    store.create_bucket(bucket)
    documents_dir = temporary / "documents"
    store.put_object(bucket, "documents.zip", _zip_directory(documents_dir, "documents"))
    for path in temporary.rglob("*"):
        if not path.is_file() or path.is_relative_to(documents_dir):
            continue
        key = path.relative_to(temporary).as_posix()
        store.put_object(bucket, key, path.read_bytes())


def _zip_directory(directory: Path, prefix: str) -> bytes:
    """把目录整棵树压进内存 zip，成员名为 <prefix>/<相对路径>，不落盘。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.writestr(f"{prefix}/{path.relative_to(directory).as_posix()}", path.read_bytes())
    return buffer.getvalue()


def _resource_refs(bucket: str) -> list[ResourceRef]:
    return [
        ResourceRef(type="documents", location=f"s3://{bucket}/documents.zip"),
        ResourceRef(type="index", location=f"s3://{bucket}/index"),
    ]


def _validate_prepared(path: Path) -> None:
    """发布前检查本次写出的清单、向量和文档引用，不向问答提供加载对象。"""
    document_root = path / "documents"
    if not document_root.is_dir():
        raise ValueError("missing documents directory")
    for item in path.rglob("*"):
        if item.is_symlink() or not item.resolve().is_relative_to(path.resolve()):
            raise ValueError("resource contains an external path")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1:
        raise ValueError("unsupported resource version")
    model_id, backend = manifest["embedding_model"], manifest["embedding_backend"]
    if not isinstance(model_id, str) or not model_id or backend not in {"openvino", "torch"}:
        raise ValueError("invalid embedding configuration")
    meta = json.loads((path / "index" / "index.json").read_text(encoding="utf-8"))
    if meta["model_id"] != model_id:
        raise ValueError("index model does not match manifest")
    vectors = np.load(path / "index" / "vectors.npy", allow_pickle=False, mmap_mode="r")
    chunks = [Chunk(**item) for item in meta["chunks"]]
    if vectors.ndim != 2 or vectors.shape != (len(chunks), meta["dimension"]) or not np.isfinite(vectors).all():
        raise ValueError("invalid index vectors")
    for chunk in chunks:
        if not chunk.covered_files:
            raise ValueError("chunk requires document references")
        for relative in chunk.covered_files:
            file = (document_root / relative).resolve()
            if Path(relative).is_absolute() or not file.is_relative_to(document_root.resolve()) or not file.is_file():
                raise ValueError("invalid index document reference")


def _document_streams(document: Path, *, roots: set[str] | None = None) -> dict[str, list[tuple[str, str]]]:
    streams = {}

    def walk(directory):
        files = []
        for child in sorted(directory.iterdir(), key=lambda item: order_key(item.name)):
            if child.is_dir():
                files.extend(walk(child))
            elif child.suffix == ".md":
                files.append((child.relative_to(document).as_posix(), child.read_text(encoding="utf-8")))
        return files

    for entry in sorted(document.iterdir(), key=lambda item: order_key(item.name)):
        if entry.is_dir() and (roots is None or entry.name in roots):
            streams[entry.name] = walk(entry)
    return streams


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def remove_published_documents(store: ObjectStore, bucket: str, removed: set[str]) -> list[ResourceRef]:
    """从既有归档和索引剔除文档，保留剩余路径及向量，不解析或调用模型。"""
    with TemporaryDirectory(prefix="document-removal-") as directory:
        temporary = Path(directory).resolve()
        manifest = _load_published(store, bucket, temporary)
        roots = _document_roots(manifest, temporary)
        removed_roots = {roots[name] for name in removed if name in roots}
        for root in removed_roots:
            target = (temporary / "documents" / root).resolve()
            if target.parent != temporary / "documents":
                raise ValueError("invalid document root")
            if target.exists():
                shutil.rmtree(target)
        meta_path = temporary / "index" / "index.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        keep = [i for i, chunk in enumerate(meta["chunks"]) if chunk["document"] not in removed_roots]
        vectors_path = temporary / "index" / "vectors.npy"
        vectors = np.load(vectors_path, allow_pickle=False)
        np.save(vectors_path, vectors[keep], allow_pickle=False)
        meta["chunks"] = [meta["chunks"][i] for i in keep]
        _write_json(meta_path, meta)
        manifest["documents"] = [name for name in manifest["documents"] if name not in removed]
        manifest["document_roots"] = {name: root for name, root in roots.items() if name not in removed}
        _write_json(temporary / "manifest.json", manifest)
        _validate_prepared(temporary)
        _publish_to_store(store, bucket, temporary)
    return _resource_refs(bucket)


def _load_published(store: ObjectStore, bucket: str, temporary: Path):
    (temporary / "documents").mkdir()
    (temporary / "index").mkdir()
    for key in ("manifest.json", "index/index.json", "index/vectors.npy"):
        data = store.get_object(bucket, key)
        if data is None:
            raise ValueError(f"missing published resource: {key}")
        (temporary / key).write_bytes(data)
    data = store.get_object(bucket, "documents.zip")
    if data is None:
        raise ValueError("missing published resource: documents.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            target = (temporary / entry.filename).resolve()
            if not target.is_relative_to(temporary / "documents"):
                raise ValueError("invalid document archive path")
            if not entry.is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
    _validate_prepared(temporary)
    manifest = json.loads((temporary / "manifest.json").read_text(encoding="utf-8"))
    return manifest


def _document_roots(manifest, temporary: Path):
    roots = manifest.get("document_roots")
    if roots is None:
        # 旧清单按上传顺序编号；首次删除时补齐映射，后续不因编号空缺而错配。
        directories = [entry.name for entry in (temporary / "documents").iterdir()]
        roots = {}
        for index, name in enumerate(manifest["documents"], start=1):
            matches = [root for root in directories if root.startswith(f"{index:03d}-")]
            if len(matches) != 1:
                raise ValueError("cannot map published document to raw file")
            roots[name] = matches[0]
    return roots
