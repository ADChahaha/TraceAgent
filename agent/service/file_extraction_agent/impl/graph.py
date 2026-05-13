"""Top-level streaming orchestration for virtual-tree extraction."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from service.file_extraction_agent.impl.html_state import GraphState, HtmlExtractionInput, build_graph_state
from service.file_extraction_agent.impl.resolution_new import run_resolution_stream
from service.file_extraction_agent.schemas import ExtractionResult


def run_extraction_graph_stream(
    extraction_input: HtmlExtractionInput,
    resolution_model: Any = None,
) -> Iterable[str]:
    state = build_graph_state(extraction_input)
    emitted = 0
    outcome: Any = {"ok": False, "errors": [{"message": "resolution did not run"}]}
    try:
        for outcome in run_resolution_stream(state, resolution_model):
            while emitted < len(state.events):
                yield json.dumps(_plain(state.events[emitted]), ensure_ascii=False) + "\n"
                emitted += 1
    except Exception as exc:
        state.failed_stage = "resolution"
        _append_failure_event(state, exc)
        outcome = {"ok": False, "errors": [{"message": str(exc)}]}

    while emitted < len(state.events):
        yield json.dumps(_plain(state.events[emitted]), ensure_ascii=False) + "\n"
        emitted += 1

    if not any(event.get("type") == "result_completed" for event in state.events):
        result = map_state_to_result(
            state,
            status="failed",
            failure_reason=_failure_reason(outcome),
        )
        event = {
            "seq": state.next_seq,
            "type": "result_completed",
            "tool": "submit_result",
            "reason": "resolution failed before successful submit_result",
            "result": result.result,
            "trace": result.trace,
        }
        state.next_seq += 1
        yield json.dumps(_plain(event), ensure_ascii=False) + "\n"


def map_state_to_result(
    state: GraphState,
    status: str = "completed",
    failure_reason: str | None = None,
) -> ExtractionResult:
    fields = [state.field_states[field.name] for field in state.task_spec.fields if field.name in state.field_states]
    trace: dict[str, Any] = {
        "events": _plain(state.events),
        "actions": _plain(state.actions),
        "document_tree": state.document.tree_text("/", depth=3),
    }
    if state.failed_stage:
        trace["failed_stage"] = state.failed_stage
    if failure_reason:
        trace["failure_reason"] = failure_reason
    return ExtractionResult(
        status=status,  # type: ignore[arg-type]
        result={"fields": _plain(fields)},
        failure_reason=failure_reason,
        trace=trace,
    )


def _append_failure_event(state: GraphState, exc: Exception) -> None:
    state.events.append(
        {
            "seq": state.next_seq,
            "type": "tool_failed",
            "tool": "resolution",
            "reason": "resolution raised an exception",
            "result": {"ok": False, "errors": [{"message": str(exc)}]},
        }
    )
    state.next_seq += 1


def _failure_reason(outcome: Any) -> str:
    if isinstance(outcome, dict):
        errors = outcome.get("errors") or []
        if errors:
            return "; ".join(str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors)
    return "resolution failed"


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


__all__ = ["run_extraction_graph_stream", "map_state_to_result"]
