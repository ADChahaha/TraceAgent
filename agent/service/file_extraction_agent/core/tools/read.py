"""`read` tool: read one `.md` block file from the workspace tree."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

from service.file_extraction_agent.core.tools.base import run_tool


def _read(state: ToolWorkspace, path: str) -> JsonObject:
    return run_tool(
        lambda: _locator_error(path) or _read_result(state, path),
    )


def _read_result(state: ToolWorkspace, path: str) -> JsonObject:
    try:
        text = state.document.read(path)
    except ValueError as exc:
        return {"ok": False, "errors": [{"code": "BAD_PATH", "message": str(exc)}]}
    return {"ok": True, "path": path, "text": text}


def _locator_error(path: str) -> JsonObject | None:
    if not isinstance(path, str) or not path.strip():
        return {
            "ok": False,
            "errors": [
                {
                    "code": "BAD_PATH",
                    "message": "请原样使用 ls 返回的 .md 对象 key，例如 documents/0001-contract/0001-section/0001-block.md",
                }
            ],
        }
    return None


def build_read(state: ToolWorkspace) -> BaseTool:
    @tool
    async def read(path: str) -> JsonObject:
        """Read one .md block file.

        path 必须原样使用 ls 返回的 .md 对象 key（例如 documents/0001-contract/0001-section/0001-block.md），
        不传本机路径或 s3:// URL。返回文件的 Markdown 内容。
        Paragraphs return plain text; lists return markdown bullets; tables
        return a markdown table. After reading, narrate what the block contains
        with actual values — then move on or cite it in your answer with a link.
        """

        return await asyncio.to_thread(_read, state, path)

    return read


__all__ = ["build_read", "_read", "_read_result", "_locator_error"]
