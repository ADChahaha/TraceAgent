"""HTML → 临时文档树与 embedding 索引 → 写清单并校验产物 → 原子发布资源路径。

prepare_resources 调用 materialize_tree、build_index；准备异常清理自己的临时目录。
已发布资源由 Agent 工具读取，本模块不提供消费端加载接口。
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np

from service.document_resources import model
from service.document_resources.documents import materialize_tree, order_key
from service.document_resources.schemas import InputDocument
from service.document_resources.index import Chunk, build_index


def resources_root() -> Path:
    return Path(os.getenv("DOCUMENT_RESOURCES_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "resources"))).resolve()


def prepare_resources(documents: list[InputDocument]) -> str:
    if not documents or any(not doc.filename.strip() or not doc.html.strip() for doc in documents):
        raise ValueError("documents require non-empty filename and html")
    parent = resources_root()
    parent.mkdir(parents=True, exist_ok=True)
    resource_id = f"res_{uuid.uuid4().hex}"
    temporary = parent / f".building-{resource_id}"
    destination = parent / resource_id
    temporary.mkdir()
    try:
        document = materialize_tree(documents, temporary / "documents")
        model_id = os.getenv("EMBEDDING_MODEL", model.DEFAULT_EMBEDDING_MODEL)
        backend = os.getenv("EMBEDDING_BACKEND", "openvino")
        chunk_size = int(os.getenv("EMBEDDING_CHUNK_SIZE", "256"))
        overlap = int(os.getenv("EMBEDDING_CHUNK_OVERLAP", "32"))
        index = build_index(
            _document_streams(document), embedder=model.get_embedder(model_id=model_id, backend=backend),
            model_id=model_id, tokenize=model.get_tokenizer(model_id),
            chunk_size=chunk_size, overlap=overlap,
        )
        index_dir = temporary / "index"
        index_dir.mkdir()
        _write_json(index_dir / "index.json", {
            "model_id": model_id, "dimension": index.dimension,
            "chunks": [asdict(chunk) for chunk in index.chunks],
        })
        np.save(index_dir / "vectors.npy", index.vectors, allow_pickle=False)
        _write_json(temporary / "manifest.json", {
            "version": 1, "embedding_model": model_id, "embedding_backend": backend,
            "chunk_size": chunk_size, "overlap": overlap,
            "documents": [doc.filename for doc in documents],
        })
        _validate_prepared(temporary)
        temporary.rename(destination)
    except BaseException:
        # 只清理本次创建且仍位于受管理根目录下的临时目录。
        if temporary.resolve().parent == parent and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    return str(destination)


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


def _document_streams(document: Path) -> dict[str, list[tuple[str, str]]]:
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
        if entry.is_dir():
            streams[entry.name] = walk(entry)
    return streams


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
