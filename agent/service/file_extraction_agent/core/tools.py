"""Model-facing tools for document QA over a real file tree."""

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

# 工具清单：只暴露 ls / grep / read。inspect 与 evidence:///path_id 协议已删除。
VALID_KINDS = {"md"}


def build_tools(state: Any) -> list[Any]:
    """Build model-facing QA navigation tools bound to the current graph state."""

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

    @tool
    def read(path: str) -> dict[str, Any]:
        """Read one .md block file.

        path MUST be an absolute path to a .md file under the workspace root,
        copied verbatim from ls output. Returns the file's markdown content.
        Paragraphs return plain text; lists return markdown bullets; tables
        return a markdown table. After reading, narrate what the block contains
        with actual values — then move on or cite it in your answer with a link.
        """

        return _read(state, path)

    return [ls, grep, read]


def _ls(state: Any, path: str = "") -> dict[str, Any]:
    return _run_tool(
        state,
        "ls",
        {"path": path},
        lambda: _ls_result(state, path),
    )


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

    return _run_tool(state, "grep", {"query": query, "scope": scope, "max_results": max_results}, execute)


def _read(state: Any, path: str) -> dict[str, Any]:
    return _run_tool(
        state,
        "read",
        {"path": path},
        lambda: _locator_error(state, path) or _read_result(state, path),
    )


def _read_result(state: Any, path: str) -> dict[str, Any]:
    try:
        text = state.document.read(path)
    except ValueError as exc:
        return {"ok": False, "errors": [{"code": "BAD_PATH", "message": str(exc)}]}
    return {"ok": True, "path": path, "text": text}


def _ls_result(state: Any, path: str) -> dict[str, Any]:
    entries = state.document.entries(path or None)
    lines = [f"{entry.name}/" if entry.kind == "dir" else entry.name for entry in entries]
    return {"ok": True, "path": path or str(state.document.root), "entries": _expose_entries(entries), "text": "\n".join(lines)}


def _expose_entries(entries: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": entry.name, "path": entry.path, "kind": entry.kind, "order": entry.order}
        for entry in entries
    ]


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


def _locator_error(state: Any, path: str) -> dict[str, Any] | None:
    del state
    if not isinstance(path, str) or not path.strip():
        return {
            "ok": False,
            "errors": [
                {
                    "code": "BAD_PATH",
                    "message": "use an absolute .md file path copied from ls output",
                }
            ],
        }
    return None


def _run_tool(state: Any, tool_name: str, args: dict[str, Any], execute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    _emit_event(
        state,
        {
            "type": "tool_started",
            "tool": tool_name,
            "args": args,
        },
    )
    try:
        result = execute()
    except Exception as exc:  # pragma: no cover - exercised by tool users
        result = {"ok": False, "errors": [{"message": str(exc)}]}
    event_type = "tool_completed" if result.get("ok") is not False else "tool_failed"
    _record_action(state, tool_name, args, result)
    _emit_event(
        state,
        {
            "type": event_type,
            "tool": tool_name,
            "args": args,
            "result": result,
        },
    )
    return result


def _record_action(state: Any, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    state.actions.append(
        {
            "tool_name": tool_name,
            "args": args,
            "result": result,
        }
    )


def _emit_event(state: Any, payload: dict[str, Any]) -> None:
    event = {"seq": state.next_seq, **payload}
    state.next_seq += 1
    state.events.append(event)


__all__ = [
    "build_tools",
    "_ls",
    "_grep",
    "_read",
]
