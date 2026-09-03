"""`search_embedding` tool (glue) for semantic candidate recall.

`core/tools/embedding/` 把 embedding 相关能力聚在一个内聚子包里：

```text
core/tools/embedding/
  -> __init__.py   search_embedding 工具（glue）+ _get_embedder + 对外转出
  -> model.py      真实 embedding 模型惰性加载（get_embedder / get_tokenizer）
  -> search.py     纯 numpy 分块/索引/余弦检索（chunk_text / build_index / search_top_k）
  -> index.py      索引持久化 + 内容哈希缓存 key + 文档流收集（_get_index）
```

`__init__.py` 对外提供 `build_search_embedding(state)`（langchain @tool 绑定的
`search_embedding`），它调用 `_search_embedding` —— 后者拿到 `_get_embedder`
（模型封装）与 `_get_index`（索引底座），对 query 编码一次做余弦 top-k 检索。

实现步骤：

```text
模型调用 search_embedding(query, top_k, scope)
  -> 校验 query 非空（空 -> BAD_QUERY）
  -> _get_embedder(state)  惰性单例（openvino/torch）—— 见 model.py
  -> _get_index(state, embedder, scope)  读取或构建索引 —— 见 index.py
  -> query_vec = embedder.encode([query])
  -> search_top_k(query_vec, index, top_k) —— 见 search.py
  -> 返回 { ok, query, scope, results: [{score, document, chunk_id, text, ...}] }
```
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
from service.file_extraction_agent.core.tools.embedding.index import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    EMBEDDING_INDEX_DIR,
    _build_streams,
    _get_index,
    _index_cache_key,
)
from service.file_extraction_agent.core.tools.embedding.model import DEFAULT_EMBEDDING_MODEL

DEFAULT_EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "openvino")


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
    from service.file_extraction_agent.core.tools.embedding.model import get_embedder

    model_id = getattr(state, "embedding_model", None) or DEFAULT_EMBEDDING_MODEL
    backend = getattr(state, "embedding_backend", None) or DEFAULT_EMBEDDING_BACKEND
    embedder = get_embedder(model_id=model_id, backend=backend)
    try:
        setattr(state, "_embedder", embedder)
    except Exception:
        pass
    return embedder


def _search_top_k(query_vec: Any, index: Any, top_k: int) -> list[dict[str, Any]]:
    from service.file_extraction_agent.core.tools.embedding.search import search_top_k

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


__all__ = [
    "build_search_embedding",
    "_search_embedding",
    "_get_embedder",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_BACKEND",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "EMBEDDING_INDEX_DIR",
]
