"""`grep` tool: full-text search across readable blocks using pure Python search.

在 ObjectStore 下按 key 前缀遍历 .md 对象，用正则匹配内容并返回候选行。
不再依赖 ripgrep 子进程。
"""

from __future__ import annotations

import asyncio
import re

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

from service.file_extraction_agent.core.tools.base import run_tool


def _grep(
    state: ToolWorkspace,
    *,
    query: str,
    scope: str = "",
    max_results: int = 20,
) -> JsonObject:
    def execute() -> JsonObject:
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "errors": [{"code": "BAD_QUERY", "message": "query is required"}]}
        output = _grep_output(state, query, scope, max_results)
        return {"ok": True, "query": query, "scope": scope, "output": output}

    return run_tool(execute)


def _grep_output(state: ToolWorkspace, query: str, scope: str, max_results: int) -> str:
    try:
        prefix = state.document.scope_path(scope or None)
    except ValueError as exc:
        return str(exc)
    bounded = max(1, min(int(max_results or 20), 50))
    try:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    except re.error:
        return "invalid query"
    keys = state.document.store.list_objects(state.document.bucket, prefix=prefix)
    lines: list[str] = []
    for key in sorted(keys):
        if not key.endswith(".md"):
            continue
        data = state.document.store.get_object(state.document.bucket, key)
        if data is None:
            continue
        content = data.decode("utf-8")
        for index, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                lines.append(f"{key}:{index}:{line}")
            if len(lines) >= bounded:
                return "\n".join(lines)
    return "\n".join(lines)


def build_grep(state: ToolWorkspace) -> BaseTool:
    @tool
    async def grep(query: str, scope: str = "", max_results: int = 20) -> JsonObject:
        """Full-text search across readable blocks.

        Use for targeted lookups: dates, names, amounts, specific terms.
        Results are candidates only — NOT final evidence. Always read a
        candidate before citing it in your answer.
        scope: optional key prefix path to limit search to a section.
        max_results: default 20, max 50.
        """

        return await asyncio.to_thread(
            _grep, state, query=query, scope=scope, max_results=max_results
        )

    return grep


__all__ = ["build_grep", "_grep", "_grep_output"]