"""根据执行输入绑定文档问答工具。

`core/tools` 包把每个工具拆成独立文件：`ls.py` / `grep.py` / `read.py` /
`embedding.py`（承载 `search_embedding`），共享骨架放 `base.py`。本 `__init__.py`
对外提供统一接口 `build_tools(workspace)`，并转出各工具的 `_ls/_grep/_read/
_search_embedding` 及可替身点 `_run_ripgrep/_get_embedder/_get_index`，供测试
monkeypatch 与外部 import 使用。

实现步骤：

```text
build_tools(workspace)
  -> build_ls(workspace)          # langchain @tool 包裹，绑定 ls
  -> build_grep(workspace)        # 绑定 grep
  -> build_read(workspace)        # 绑定 read
  -> build_search_embedding(workspace)  # 绑定 search_embedding
  -> 返回 [ls, grep, read, search_embedding]
```

工具由 `base.run_tool` 执行并归一化异常，只返回结果；对外事件由 completion_runtime 包装。
"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.core.tools.embedding import (
    DEFAULT_EMBEDDING_BACKEND,
    DEFAULT_EMBEDDING_MODEL,
    _get_embedder,
    _get_index,
    _search_embedding,
    build_search_embedding,
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

from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

VALID_KINDS = {"md"}


def build_tools(workspace: ToolWorkspace) -> list[Any]:
    """工具访问上下文 → 四个共享文档与 embedding 访问器的工具。"""
    return [build_ls(workspace), build_grep(workspace), build_read(workspace), build_search_embedding(workspace)]


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
    "_get_embedder",
    "_get_index",
    "_run_ripgrep",
    "run_tool",
    "expose_entries",
    "order_key",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_BACKEND",
    "VALID_KINDS",
]
