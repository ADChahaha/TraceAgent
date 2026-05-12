"""Top-level orchestration for the HTML extraction flow."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from service.file_extraction_agent.impl.html_state import GraphState, HtmlExtractionInput, build_graph_state
from service.file_extraction_agent.impl.resolution_new import run_resolution
from service.file_extraction_agent.schemas import ExtractionResult


def run_extraction_graph(
    extraction_input: HtmlExtractionInput,
    resolution_model: Any = None,
    **legacy_kwargs: Any,
) -> ExtractionResult:
    resolution_model = (
        resolution_model if resolution_model is not None else legacy_kwargs.get("resolution_client")
    )
    state = build_graph_state(extraction_input)

    try:
        outcome = run_resolution(state, resolution_model)
    except Exception as exc:
        return build_failed_result(state, "resolution", exc)

    if isinstance(outcome, dict) and outcome.get("ok") is False:
        reason = _failure_reason(outcome)
        state.failed_stage = "resolution"
        return map_state_to_result(state, status="failed", failure_reason=reason)

    return map_state_to_result(state)


def map_state_to_result(
    state: GraphState,
    status: str = "completed",
    failure_reason: str | None = None,
) -> ExtractionResult:
    result = {
        name: field_state.get("value")
        for name, field_state in state.field_states.items()
        if field_state.get("status") == "resolved"
    }
    trace: dict[str, Any] = {
        "plan_statuses": _plain(state.plan_statuses),
        "document_tree": _plain(state.document.tree),
        "field_states": _plain(state.field_states),
        "notes": _plain(getattr(state, "notes", [])),
        "actions": _plain(state.actions),
    }
    failed_stage = getattr(state, "failed_stage", None)
    if failed_stage:
        trace["failed_stage"] = failed_stage
    if failure_reason:
        trace["failure_reason"] = failure_reason
    return ExtractionResult(
        status=status,  # type: ignore[arg-type]
        result=result,
        failure_reason=failure_reason,
        trace=trace,
    )


def build_failed_result(state: GraphState, stage: str, exc: Exception) -> ExtractionResult:
    state.failed_stage = stage
    return map_state_to_result(state, status="failed", failure_reason=str(exc))


def _failure_reason(outcome: dict[str, Any]) -> str:
    errors = outcome.get("errors") or []
    if not errors:
        return "resolution failed"
    return "; ".join(str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors)


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "run_extraction_graph",
    "map_state_to_result",
    "build_failed_result",
]
