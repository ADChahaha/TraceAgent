"""`ls` tool: list one level of the document workspace tree.

同步叶子逻辑在工具子进程中执行；父进程工具只通过 run_operation 下发参数和 workspace。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

from service.file_extraction_agent.core.tools.base import expose_entries, run_tool
from service.file_extraction_agent.core.tools.worker_client import run_operation


def _ls(state: ToolWorkspace, path: str = "") -> JsonObject:
    return run_tool(
        lambda: _ls_result(state, path),
    )


def _ls_result(state: ToolWorkspace, path: str) -> JsonObject:
    entries = state.document.entries(path or None)
    lines = [f"{entry.name}/" if entry.kind == "dir" else entry.name for entry in entries]
    return {
        "ok": True,
        "path": path or state.document.root_key,
        "entries": expose_entries(entries),
        "text": "\n".join(lines),
    }


def build_ls(workspace: dict[str, Any], *, run_operation=run_operation) -> BaseTool:
    @tool
    async def ls(path: str = "") -> JsonObject:
        """List one level of the document workspace at a directory path.

        Use this to see document structure. Leave path empty for the root,
        或原样传入上次 ls 返回的目录 key（例如 documents/0001-contract）。
        Directory names show a trailing slash in ls output.
        ls returns only direct child directories and .md block files; it does
        NOT recursively expand descendants and does NOT return file text.
        To get content, call read on a child file path.
        Start every investigation here to understand document layout before reading.
        """

        return await run_operation(operation="ls", args={"path": path}, workspace=workspace)

    return ls


__all__ = ["build_ls", "_ls", "_ls_result"]
