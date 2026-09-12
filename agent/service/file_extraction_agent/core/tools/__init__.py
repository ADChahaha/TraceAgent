"""根据 workspace payload 绑定文档问答工具。

`core/tools` 包把每个工具拆成独立文件：`ls.py` / `grep.py` / `read.py` /
`embedding.py`（承载 `search_embedding`），共享骨架放 `base.py`。
本 `__init__.py` 对外提供统一接口 `build_tools(workspace)`：四个工具都只通过
`worker_client.run_operation` 把 operation、参数和全量 workspace 下发给子进程执行，
父进程不再持有 ObjectStore 或索引。

实现步骤：

```text
build_tools(workspace)
  -> build_ls(workspace)                # langchain @tool 包裹，子进程执行 ls
  -> build_grep(workspace)              # 子进程执行 grep
  -> build_read(workspace)              # 子进程执行 read
  -> build_search_embedding(workspace)  # 子进程执行 search_embedding
  -> 返回 [ls, grep, read, search_embedding]
```
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from service.file_extraction_agent.core.tools.embedding import (
    build_search_embedding,
    index_to_payload,
    search_top_k,
)
from service.file_extraction_agent.core.tools.grep import (
    _grep,
    _grep_output,
    build_grep,
)
from service.file_extraction_agent.core.tools.ls import _ls, _ls_result, build_ls
from service.file_extraction_agent.core.tools.read import (
    _read,
    _read_result,
    _locator_error,
    build_read,
)

from service.file_extraction_agent.core.tools.base import (
    expose_entries,
    order_key,
    run_tool,
)

from service.file_extraction_agent.core.tools.worker_client import prepare_workspace, run_operation


def build_tools(workspace: dict[str, Any], *, run_operation=run_operation) -> list[BaseTool]:
    """workspace payload → 四个在工具子进程中执行的文档与检索工具。"""
    return [
        build_ls(workspace, run_operation=run_operation),
        build_grep(workspace, run_operation=run_operation),
        build_read(workspace, run_operation=run_operation),
        build_search_embedding(workspace, run_operation=run_operation),
    ]


__all__ = [
    "build_tools",
    "prepare_workspace",
    "_ls",
    "_grep",
    "_read",
    "_ls_result",
    "_grep_output",
    "_read_result",
    "_locator_error",
    "index_to_payload",
    "search_top_k",
    "run_tool",
    "expose_entries",
    "order_key",
]
