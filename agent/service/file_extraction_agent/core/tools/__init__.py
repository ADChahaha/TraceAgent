"""Unified surface for model-facing document-QA tools.

`core/tools` 包把每个工具拆成独立文件：`ls.py` / `grep.py` / `read.py` /
`embedding.py`（承载 `search_embedding`），共享骨架放 `base.py`。本 `__init__.py`
对外提供统一接口 `build_tools(state)`，并转出各工具的 `_ls/_grep/_read/
_search_embedding` 及可替身点 `_run_ripgrep/_get_embedder/_get_index`，供测试
monkeypatch 与外部 import 使用。

实现步骤：

```text
build_tools(state)
  -> build_ls(state)          # langchain @tool 包裹，绑定 ls
  -> build_grep(state)        # 绑定 grep
  -> build_read(state)        # 绑定 read
  -> build_search_embedding(state)  # 绑定 search_embedding
  -> 返回 [ls, grep, read, search_embedding]
```

工具由 `base.run_tool` 执行并归一化异常，只返回结果；对外事件由 manager 包装。
"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.core.tools.embedding import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EMBEDDING_BACKEND,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_INDEX_DIR,
    _get_embedder,
    _search_embedding,
    build_search_embedding,
)
from service.file_extraction_agent.core.tools.embedding.index import (
    _build_streams,
    _get_index,
    _index_cache_key,
)
from service.file_extraction_agent.core.tools.grep import (
    _grep,
    _grep_output,
    _run_ripgrep,
    build_grep,
)
from service.file_extraction_agent.core.tools.ls import _ls, _ls_result, build_ls
from service.file_extraction_agent.core.tools.read import _read, _read_result, _locator_error, build_read

# 对外公开的配置常量（供读取与测试断言）
from service.file_extraction_agent.core.tools.base import (
    expose_entries,
    order_key,
    run_tool,
)

VALID_KINDS = {"md"}


def build_tools(state: Any) -> list[Any]:
    """Build model-facing QA navigation tools bound to the current graph state."""

    return [build_ls(state), build_grep(state), build_read(state), build_search_embedding(state)]


__all__ = [
    "build_tools",
    "_ls",
    "_grep",
    "_read",
    "_search_embedding",
    "_ls_result",
    "_grep_output",
    "_read_result",
    "_locator_error",
    "_build_streams",
    "_get_embedder",
    "_get_index",
    "_run_ripgrep",
    "run_tool",
    "expose_entries",
    "order_key",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_BACKEND",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "EMBEDDING_INDEX_DIR",
    "VALID_KINDS",
]
