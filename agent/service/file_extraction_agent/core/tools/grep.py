"""`grep` tool: full-text search across readable blocks using ripgrep."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function

from service.file_extraction_agent.core.tools.base import run_tool


def _grep(
    state: Any,
    *,
    query: str,
    scope: str = "",
    max_results: int = 20,
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "errors": [{"code": "BAD_QUERY", "message": "query is required"}]}
        output = _grep_output(state, query, scope, max_results)
        if output is None:
            return {"ok": False, "errors": [{"code": "RIPGREP_MISSING", "message": "ripgrep not found on PATH"}]}
        return {"ok": True, "query": query, "scope": scope, "output": output}

    return run_tool(state, "grep", {"query": query, "scope": scope, "max_results": max_results}, execute)


def _grep_output(state: Any, query: str, scope: str, max_results: int) -> str | None:
    try:
        scope_dir = state.document.scope_path(scope or None)
    except ValueError as exc:
        return str(exc)
    bounded = max(1, min(int(max_results or 20), 50))
    return _run_ripgrep(query, scope_dir, bounded)


def _run_ripgrep(query: str, scope_dir: Path, max_results: int) -> str | None:
    import shutil
    import subprocess

    rg = shutil.which("rg")
    if rg is None:
        return None
    command = [rg, "-n", "--color", "never", "--max-count", str(max_results), query, "."]
    completed = subprocess.run(
        command,
        cwd=str(scope_dir),
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 1):
        return completed.stderr.strip() or "ripgrep failed"
    return completed.stdout


def build_grep(state: Any) -> Callable:
    @tool
    def grep(query: str, scope: str = "", max_results: int = 20) -> dict[str, Any]:
        """Full-text search across readable blocks using ripgrep.

        Use for targeted lookups: dates, names, amounts, specific terms.
        Results are candidates only — NOT final evidence. Always read a
        candidate before citing it in your answer.
        scope: optional directory path to limit search to a section.
        max_results: default 20, max 50.
        """

        return _grep(state, query=query, scope=scope, max_results=max_results)

    return grep


__all__ = ["build_grep", "_grep", "_grep_output", "_run_ripgrep"]
