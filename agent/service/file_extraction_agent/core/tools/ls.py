"""`ls` tool: list one level of the document workspace tree."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

from service.file_extraction_agent.core.tools.base import expose_entries, run_tool


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


def build_ls(state: ToolWorkspace) -> BaseTool:
    @tool
    async def ls(path: str = "") -> JsonObject:
        """List one level of the document workspace at a directory path.

        Use this to see document structure. Leave path empty for the root,
        or pass an absolute directory path returned by a previous ls.
        Directory names show a trailing slash in ls output.
        ls returns only direct child directories and .md block files; it does
        NOT recursively expand descendants and does NOT return file text.
        To get content, call read on a child file path.
        Start every investigation here to understand document layout before reading.
        """

        return await asyncio.to_thread(_ls, state, path)

    return ls


__all__ = ["build_ls", "_ls", "_ls_result"]
