"""`grep` tool: full-text search across readable blocks using pure Python search.

同步叶子逻辑在工具子进程中执行；父进程工具只通过 run_operation 下发参数和 workspace。
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

from service.file_extraction_agent.core.tools.base import run_tool
from service.file_extraction_agent.core.tools.worker_client import run_operation


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


def build_grep(workspace: dict[str, Any], *, run_operation=run_operation) -> BaseTool:
    @tool
    async def grep(query: str, scope: str = "", max_results: int = 20) -> JsonObject:
        """Full-text search across readable blocks.

        Use for targeted lookups: dates, names, amounts, specific terms.
        Results are candidates only — NOT final evidence. Always read a
        candidate before citing it in your answer.
        scope: optional key prefix path to limit search to a section.
        max_results: default 20, max 50.
        """

        return await run_operation(
            operation="grep",
            args={"query": query, "scope": scope, "max_results": max_results},
            workspace=workspace,
        )

    return grep


__all__ = ["build_grep", "_grep", "_grep_output"]