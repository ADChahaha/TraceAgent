"""`read` tool: read one `.md` block file from the workspace tree."""

from __future__ import annotations

from typing import Any, Callable

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function

from service.file_extraction_agent.core.tools.base import run_tool


def _read(state: Any, path: str) -> dict[str, Any]:
    return run_tool(
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


def build_read(state: Any) -> Callable:
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

    return read


__all__ = ["build_read", "_read", "_read_result", "_locator_error"]
