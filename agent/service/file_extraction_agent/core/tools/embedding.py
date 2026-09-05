"""语义检索：资源路径 → 校验并加载已有索引 → 按清单加载查询模型 → 编码 query → top-k 候选。

本文件集中管理 Agent 的 embedding 配置读取、索引加载、模型缓存与检索。
不生成文档向量；损坏索引抛 ValueError，工具调用通过 run_tool 转成失败结果。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function

from service.file_extraction_agent.core.tools.base import run_tool

DEFAULT_EMBEDDING_MODEL = "hotchpotch/bekko-embedding-v1-a8m"

DEFAULT_EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "openvino")


@dataclass
class Chunk:
    """检索命中单元：一个固定 token 窗口切出的文本片段。"""

    document: str
    chunk_id: str
    text: str
    token_range: tuple[int, int] = (0, 0)
    char_range: tuple[int, int] = (0, 0)
    covered_files: list[str] = field(default_factory=list)


@dataclass
class EmbeddingIndex:
    """一个文档集的向量索引。"""

    model_id: str
    chunks: list[Chunk]
    vectors: np.ndarray
    dimension: int = 0


_model_cache: dict[tuple[str, str], Any] = {}
_model_lock = threading.Lock()


def get_embedder(*, model_id: str, backend: str) -> Any:
    """按清单配置惰性创建查询编码器，按模型与后端缓存，不加载文档生成模块。"""
    key = (model_id, backend)
    with _model_lock:
        if key not in _model_cache:
            from sentence_transformers import SentenceTransformer

            options = {"trust_remote_code": True}
            if backend == "openvino":
                options["backend"] = "openvino"
            _model_cache[key] = SentenceTransformer(model_id, **options)
        return _model_cache[key]


class EmbeddingResources:
    """资源目录 → 校验并缓存清单/索引 → 惰性加载查询模型；并行工具共用同轮缓存。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.model_id: str | None = None
        self.backend: str | None = None
        self._index: EmbeddingIndex | None = None
        self._model: Any = None
        self._lock = threading.RLock()

    def load_index(self) -> EmbeddingIndex:
        """读取清单和 numpy 索引 → 校验版本、维度及引用 → 缓存只读索引；失败抛 ValueError。"""
        with self._lock:
            if self._index is None:
                try:
                    self._index = self._read_index()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"invalid document resource: {exc}") from exc
            return self._index

    def _read_index(self) -> EmbeddingIndex:
        manifest = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        if manifest["version"] != 1:
            raise ValueError("unsupported resource version")
        model_id, backend = manifest["embedding_model"], manifest["embedding_backend"]
        if not isinstance(model_id, str) or not model_id or backend not in {"openvino", "torch"}:
            raise ValueError("invalid embedding configuration")
        meta = json.loads((self.path / "index" / "index.json").read_text(encoding="utf-8"))
        if meta["model_id"] != model_id:
            raise ValueError("index model does not match manifest")
        vectors = np.load(self.path / "index" / "vectors.npy", allow_pickle=False, mmap_mode="r")
        chunks = [Chunk(**item) for item in meta["chunks"]]
        if vectors.ndim != 2 or vectors.shape != (len(chunks), meta["dimension"]) or not np.isfinite(vectors).all():
            raise ValueError("invalid index vectors")
        document_root = (self.path / "documents").resolve()
        resolved_chunks = []
        for chunk in chunks:
            if not chunk.covered_files:
                raise ValueError("chunk requires document references")
            files = []
            for relative in chunk.covered_files:
                file = (document_root / relative).resolve()
                if Path(relative).is_absolute() or not file.is_relative_to(document_root) or not file.is_file():
                    raise ValueError("invalid index document reference")
                files.append(str(file))
            resolved_chunks.append(replace(chunk, covered_files=files))
        self.model_id, self.backend = model_id, backend
        return EmbeddingIndex(model_id, resolved_chunks, vectors, meta["dimension"])

    def get_model(self) -> Any:
        """先取得清单配置，再创建查询模型；不编码文档、不重建索引。"""
        with self._lock:
            self.load_index()
            if self._model is None:
                self._model = get_embedder(model_id=self.model_id, backend=self.backend)
            return self._model


def search_top_k(query_vec: np.ndarray, index: EmbeddingIndex, top_k: int = 5) -> list[dict[str, Any]]:
    """余弦检索，返回按分数降序的候选 chunk 列表。"""

    if index.vectors.size == 0 or index.vectors.ndim != 2:
        return []
    query = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    _normalize(query)
    if index.vectors.shape[1] != query.shape[0]:
        raise ValueError("query dimension does not match index vectors")
    scores = index.vectors @ query
    order = np.argsort(-scores)[: max(0, top_k)]
    results: list[dict[str, Any]] = []
    for position in order:
        score = float(scores[position])
        chunk = index.chunks[int(position)]
        results.append(
            {
                "score": score,
                "document": chunk.document,
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "token_range": list(chunk.token_range),
                "covered_files": list(chunk.covered_files),
            }
        )
    return results


def _normalize(matrix: np.ndarray) -> None:
    if matrix.ndim == 1:
        norm = np.linalg.norm(matrix)
        if norm > 0:
            matrix /= norm
        return
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    matrix /= norms


def _get_index(state: Any, embedder: Any, scope: str = "") -> Any:
    """加载或复用工具上下文中的已有索引，问答期间不构建文档向量。"""
    return state.embedding.load_index()


def _search_embedding(
    state: Any,
    *,
    query: str,
    top_k: int = 5,
    scope: str = "",
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "errors": [{"code": "BAD_QUERY", "message": "query is required"}]}
        top_k_bounded = max(1, min(int(top_k or 5), 20))
        embedder = _get_embedder(state)
        index = _get_index(state, embedder, scope)
        query_vec = embedder.encode([query])
        results = _search_top_k(query_vec, index, top_k_bounded)
        return {"ok": True, "query": query, "scope": scope, "results": results}

    return run_tool(
        state,
        "search_embedding",
        {"query": query, "top_k": top_k, "scope": scope},
        execute,
    )


def _get_embedder(state: Any) -> Any:
    """使用工具上下文的清单配置，返回本轮缓存的查询模型。"""
    return state.embedding.get_model()


def _search_top_k(query_vec: Any, index: Any, top_k: int) -> list[dict[str, Any]]:
    return search_top_k(query_vec, index, top_k)


def build_search_embedding(state: Any) -> Callable:
    @tool
    def search_embedding(query: str, top_k: int = 5, scope: str = "") -> dict[str, Any]:
        """Semantic search across chunks using embeddings.

        Returns up to top_k text chunks that are semantically (not just
        lexically) related to query. Use when grep returns nothing useful or
        when the answer's wording differs from the document's wording.
        Chunks are fixed windows that may span multiple .md block files — each
        result carries a `document` (source doc name) and `covered_files` (the
        .md block paths the chunk spans), so you can read them to verify and
        cite. Each result also includes the chunk `text` directly.
        Results are candidates only, NOT final evidence. Always read a covered
        file before citing it in your answer.
        """

        return _search_embedding(state, query=query, top_k=top_k, scope=scope)

    return search_embedding


__all__ = ["build_search_embedding", "_search_embedding", "_get_embedder", "_get_index"]
