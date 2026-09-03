"""`ls` tool: list one level of the document workspace tree."""

from __future__ import annotations

from typing import Any, Callable

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function

from service.file_extraction_agent.core.tools.base import expose_entries, run_tool


def _ls(state: Any, path: str = "") -> dict[str, Any]:
    return run_tool(
        state,
        "ls",
        {"path": path},
        lambda: _ls_result(state, path),
    )


def _ls_result(state: Any, path: str) -> dict[str, Any]:
    entries = state.document.entries(path or None)
    lines = [f"{entry.name}/" if entry.kind == "dir" else entry.name for entry in entries]
    return {
        "ok": True,
        "path": path or str(state.document.root),
        "entries": expose_entries(entries),
        "text": "\n".join(lines),
    }


def build_ls(state: Any) -> Callable:
    @tool
    def ls(path: str = "") -> dict[str, Any]:
        """List one level of the document workspace at a directory path.

        Use this to see document structure. Leave path empty for the root,
        or pass an absolute directory path returned by a previous ls.
        Directory names show a trailing slash in ls output.
        ls returns only direct child directories and .md block files; it does
        NOT recursively expand descendants and does NOT return file text.
        To get content, call read on a child file path.
        Start every investigation here to understand document layout before reading.
        """

        return _ls(state, path)

    return ls


__all__ = ["build_ls", "_ls", "_ls_result"]
