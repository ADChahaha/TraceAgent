"""语义检索工具：校验 query → 使用资源配置编码查询 → 检索已加载索引 → 候选引用。

文档分块与索引构建位于 document_resources；工具失败通过 run_tool 返回错误结果。
"""

from __future__ import annotations

import os
from typing import Any, Callable

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function

from service.file_extraction_agent.core.tools.base import run_tool
from service.document_resources.model import DEFAULT_EMBEDDING_MODEL
from service.document_resources import model as embedding_model
from service.document_resources.search import search_top_k

DEFAULT_EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "openvino")


def _get_index(state: Any, embedder: Any, scope: str = "") -> Any:
    """只返回已加载的资源索引；问答期间不构建文档向量。"""
    return state.index


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
    """Return a cached embedding model, initializing lazily on first use.

    The real model is only imported here (never at module import time) so unit
    tests can run without torch / OpenVINO installed. Tests replace this
    function to inject a fake embedder.
    """

    cached = getattr(state, "_embedder", None)
    if cached is not None:
        return cached
    model_id = getattr(state, "embedding_model", None) or DEFAULT_EMBEDDING_MODEL
    backend = getattr(state, "embedding_backend", None) or DEFAULT_EMBEDDING_BACKEND
    embedder = embedding_model.get_embedder(model_id=model_id, backend=backend)
    try:
        setattr(state, "_embedder", embedder)
    except Exception:
        pass
    return embedder


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
