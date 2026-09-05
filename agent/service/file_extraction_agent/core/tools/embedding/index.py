"""Embedding index persistence, cache-keying, and document-stream assembly.

`index.py` 负责 embedding 索引的读取、构建落盘、内容哈希缓存 key 计算，以及从
当前 workspace 文件树收集分块输入（`_build_streams`）。它是 `search_embedding`
工具的检索底座：把 `model.py` 的模型封装和 `search.py` 的纯算法通过磁盘索引
衔接起来，保证同一文档只建一次索引、跨会话复用。

实现步骤：

```text
_get_index(state, embedder, scope)
  -> _build_streams(state) 收集 {document_name: [(md_path, text), ...]}
  -> 空文档集 -> 返回空索引
  -> 否则按内容哈希 key 读磁盘缓存
       ├─ 命中 -> 直接复用（不重新 embed）
       └─ 未命中 -> build_index(...) 构建 + _save_index 落盘 + 返回

index cache key = sha256(task_id + model_id + backend + 文档相对路径与内容 + chunk_size + overlap)
```

环境配置：

- `EMBEDDING_INDEX_DIR`：索引持久化目录，默认 `agent/data/embedding_index`。
"""

from __future__ import annotations

import os
from dataclasses import replace
import shutil
from pathlib import Path
from typing import Any

from service.file_extraction_agent.core.documents import order_key

DEFAULT_CHUNK_SIZE = int(os.getenv("EMBEDDING_CHUNK_SIZE", "256"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("EMBEDDING_CHUNK_OVERLAP", "32"))
EMBEDDING_INDEX_DIR = os.getenv(
    "EMBEDDING_INDEX_DIR",
    str(Path(__file__).resolve().parents[5] / "data" / "embedding_index"),
)


def _get_index(state: Any, embedder: Any, scope: str = "") -> Any:
    """文件树 → 任务和文档版本键 → 读缓存或编码落盘 → 将相对引用映射到本轮目录。"""

    streams = _build_streams(state)
    if not streams:
        return _empty_index()
    from service.file_extraction_agent.core.tools.embedding.model import (
        DEFAULT_EMBEDDING_MODEL,
        get_tokenizer,
    )
    from service.file_extraction_agent.core.tools.embedding.search import build_index

    model_id = getattr(state, "embedding_model", None) or DEFAULT_EMBEDDING_MODEL
    root = state.document.root.resolve()
    streams = {
        document: [(Path(path).relative_to(root).as_posix(), text) for path, text in files]
        for document, files in streams.items()
    }
    task_id = getattr(state, "task_id", None) or state.completion_id
    backend = getattr(state, "embedding_backend", None) or os.getenv("EMBEDDING_BACKEND", "openvino")
    cache_key = _index_cache_key(streams, model_id, task_id=task_id, backend=backend)
    index = _load_index(cache_key)
    if index is None:
        tokenizer = get_tokenizer(model_id)
        index = build_index(
            streams,
            embedder=embedder,
            model_id=model_id,
            tokenize=tokenizer,
            chunk_size=DEFAULT_CHUNK_SIZE,
            overlap=DEFAULT_CHUNK_OVERLAP,
        )
        _save_index(
            cache_key,
            index,
            backend,
            model_id,
        )
    # 缓存只保存相对路径；返回时绑定本轮 workspace，不能复用旧 completion 的绝对路径。
    return replace(index, chunks=[
        replace(chunk, covered_files=[str(root / path) for path in chunk.covered_files])
        for chunk in index.chunks
    ])


def _build_streams(state: Any) -> dict[str, list[tuple[str, str]]]:
    """Group all .md block files under the workspace root by source document name.

    Each document directory contributes a list of (absolute_md_path, text) in
    tree order; this is the input to embedding chunking (document-local).
    """

    streams: dict[str, list[tuple[str, str]]] = {}
    try:
        for entry in state.document.entries():
            if entry.kind != "dir":
                continue
            document_name = entry.name
            files = _md_files_under(Path(entry.path))
            if files:
                streams[document_name] = files
    except Exception:
        return streams
    return streams


def _md_files_under(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def walk(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda p: order_key(p.name)):
            if child.is_dir():
                walk(child)
            elif child.is_file() and child.suffix == ".md":
                found.append((str(child), child.read_text(encoding="utf-8")))

    walk(root)
    return found


def _index_cache_key(
    streams: dict[str, list[tuple[str, str]]], model_id: str, *, task_id: str = "", backend: str = "",
) -> str:
    import hashlib
    import json

    payload = {
        "version": 2, "task_id": task_id, "backend": backend, "model": model_id,
        "chunk_size": DEFAULT_CHUNK_SIZE, "overlap": DEFAULT_CHUNK_OVERLAP, "documents": {},
    }
    for document_name, files in streams.items():
        hashes = [hashlib.sha256(f"{path}\0{text}".encode("utf-8")).hexdigest() for path, text in files]
        payload["documents"][document_name] = hashes
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest


def _index_dir(key: str) -> Path:
    return Path(EMBEDDING_INDEX_DIR) / key


def _load_index(key: str) -> Any | None:
    import json

    directory = _index_dir(key)
    index_path = directory / "index.json"
    vectors_path = directory / "vectors.npy"
    if not index_path.exists() or not vectors_path.exists():
        return None
    try:
        meta = json.loads(index_path.read_text(encoding="utf-8"))
        vectors = _load_vectors(vectors_path)
    except Exception:
        return None
    from service.file_extraction_agent.core.tools.embedding.search import Chunk, EmbeddingIndex

    chunks = [
        Chunk(
            document=item["document"],
            chunk_id=item["chunk_id"],
            text=item["text"],
            token_range=tuple(item["token_range"]),
            char_range=tuple(item.get("char_range", item["token_range"])),
            covered_files=item["covered_files"],
        )
        for item in meta["chunks"]
    ]
    return EmbeddingIndex(
        model_id=meta["model_id"], chunks=chunks, vectors=vectors, dimension=meta.get("dimension", 0)
    )


def _save_index(key: str, index: Any, backend: str, model_id: str) -> None:
    import json

    directory = _index_dir(key)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        meta = {"model_id": model_id, "backend": backend, "dimension": int(index.dimension)}
        meta["chunks"] = [
            {
                "document": chunk.document,
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "token_range": list(chunk.token_range),
                "char_range": list(chunk.char_range),
                "covered_files": chunk.covered_files,
            }
            for chunk in index.chunks
        ]
        (directory / "index.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        _save_vectors(directory / "vectors.npy", index.vectors)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)


def _save_vectors(path: Path, vectors: Any) -> None:
    import numpy as np

    np.save(path, np.asarray(vectors, dtype=np.float32))


def _load_vectors(path: Path) -> Any:
    import numpy as np

    return np.load(path)


def _empty_index() -> Any:
    import numpy as np

    from service.file_extraction_agent.core.tools.embedding.search import EmbeddingIndex

    return EmbeddingIndex(model_id="", chunks=[], vectors=np.zeros((0, 0), dtype=np.float32), dimension=0)


__all__ = [
    "_get_index",
    "_build_streams",
    "_index_cache_key",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "EMBEDDING_INDEX_DIR",
]
