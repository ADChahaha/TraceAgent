"""Top-level streaming orchestration for document QA completions."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from service.file_extraction_agent.impl.html_state import DocumentQaCompletionInput, GraphState, build_graph_state
from service.file_extraction_agent.impl.resolution_new import run_resolution_stream


def run_completion_graph_stream(
    completion_input: DocumentQaCompletionInput,
    resolution_model: Any = None,
) -> Iterable[str]:
    state = build_graph_state(completion_input)
    emitted = 0
    _append_completion_event(state, "completion.created", status="in_progress")
    _append_source_index_event(state)
    while emitted < len(state.events):
        yield _sse(state.events[emitted])
        emitted += 1

    outcome: Any = {"ok": False, "errors": [{"message": "resolution did not run"}]}
    try:
        for outcome in run_resolution_stream(state, resolution_model):
            while emitted < len(state.events):
                yield _sse(state.events[emitted])
                emitted += 1
    except Exception as exc:
        state.failed_stage = "resolution"
        _append_failure_event(state, exc)
        outcome = {"ok": False, "errors": [{"message": str(exc)}]}

    while emitted < len(state.events):
        yield _sse(state.events[emitted])
        emitted += 1

    if _resolution_failed(outcome):
        _append_completion_event(state, "completion.failed", status="failed", error=_failure_reason(outcome))
    else:
        _append_completion_event(state, "completion.completed", status="completed")
    yield _sse(state.events[-1])


def _append_completion_event(
    state: GraphState,
    event_type: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "seq": state.next_seq,
        "id": state.completion_id,
        "type": event_type,
        "status": status,
    }
    if error:
        payload["error"] = error
    state.next_seq += 1
    state.events.append(payload)


def _append_failure_event(state: GraphState, exc: Exception) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "tool_failed",
            "tool": "resolution",
            "result": {"ok": False, "errors": [{"message": str(exc)}]},
        }
    )
    state.next_seq += 1


def _append_source_index_event(state: GraphState) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "source_indexed",
            "tool": "source_index",
            "result": {
                "ok": True,
                "workspace_root": str(state.document.root),
                "tree": _file_tree_lines(state.document),
            },
        }
    )
    state.next_seq += 1


def _file_tree_lines(document: Any) -> list[str]:
    lines: list[str] = []

    def walk(path: str | None, prefix: str) -> None:
        entries = document.entries(path)
        for index, entry in enumerate(entries):
            current_last = index == len(entries) - 1
            connector = "└── " if current_last else "├── "
            suffix = "/" if entry.kind == "dir" else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.kind == "dir":
                next_prefix = prefix + ("    " if current_last else "│   ")
                walk(entry.path, next_prefix)

    walk(None, "")
    return lines


def _resolution_failed(outcome: Any) -> bool:
    return isinstance(outcome, dict) and outcome.get("ok") is False


def _failure_reason(outcome: Any) -> str:
    if isinstance(outcome, dict):
        errors = outcome.get("errors") or []
        if errors:
            return "; ".join(str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors)
    return "resolution failed"


def _sse(event: dict[str, Any]) -> str:
    event_type = event.get("type", "message")
    data = json.dumps(_plain(event), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n"


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


__all__ = ["run_completion_graph_stream"]
