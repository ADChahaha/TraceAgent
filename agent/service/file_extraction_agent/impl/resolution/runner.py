"""resolution 阶段 runner。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.resolution.prompts import build_resolution_messages
from service.file_extraction_agent.impl.schemas import (
    FieldDecision,
    FieldResolutionAction,
    ToolActionRecord,
)
from service.file_extraction_agent.impl.state import GraphState, record_action
from service.file_extraction_agent.impl.tools.candidates import (
    add_resolution_candidate,
    count_field_candidates,
    get_candidate_bundle,
)
from service.file_extraction_agent.impl.tools.search import search_grep
from service.file_extraction_agent.schemas import FieldDefinition


RESOLUTION_TOOLS = [
    "get_candidate_bundle",
    "search_grep",
    "add_resolution_candidate",
    "count_field_candidates",
]


def run_resolution_stage(*, state: GraphState, extractor_client: Any) -> GraphState:
    """运行共享 resolution loop，直到所有字段都有 final_decision。"""

    tool_results: list[Any] = []
    for _ in range(_shared_iteration_limit(state=state, option_name="max_resolution_iterations")):
        pending_field_names = _pending_resolution_field_names(state)
        if not pending_field_names:
            return state

        action = _invoke_client(
            extractor_client=extractor_client,
            output_schema=FieldResolutionAction,
            messages=build_resolution_messages(
                state=state,
                tool_results=tool_results,
            ),
            tools=RESOLUTION_TOOLS,
        )
        _ensure_known_field(state=state, field_name=action.field_name)

        if action.action == "count_field_candidates":
            counted_field_name = action.field_name
            tool_results = count_field_candidates(
                state=state,
                field_name=counted_field_name,
                stage="resolution",
                reason=action.reason,
            )
            continue

        if action.field_name in state.field_decisions:
            raise ValueError("resolution action field_name already has final decision")

        if action.action == "get_candidate_bundle":
            tool_results = get_candidate_bundle(state=state, field_name=action.field_name)
            continue
        if action.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            tool_results = search_grep(
                state=state,
                field_name=action.field_name,
                query=action.query or "",
                stage="resolution",
            )
            continue
        if action.action == "add_resolution_candidate":
            try:
                tool_results = add_resolution_candidate(
                    state=state,
                    field_name=action.field_name,
                    refs=list(action.refs),
                    values=list(action.values),
                    reason=action.reason or "",
                )
            except ValueError as exc:
                tool_results = _record_tool_error(
                    state=state,
                    field_name=action.field_name,
                    tool_name=action.action,
                    refs=list(action.refs),
                    error=exc,
                )
            continue
        field = _field_by_name(state=state, field_name=action.field_name)
        decision = build_field_decision_from_final_action(
            state=state,
            field=field,
            action=action,
        )
        state.field_decisions[field.field_name] = decision

    pending = ", ".join(_pending_resolution_field_names(state))
    raise ValueError(
        "resolution model did not finish all fields before iteration limit"
        f"; pending fields: {pending}"
    )


def run_resolution_loop_for_field(
    *,
    state: GraphState,
    field: FieldDefinition,
    extractor_client: Any,
) -> FieldDecision:
    """兼容旧内部调用：运行共享 resolution loop 后返回指定字段定案。"""

    run_resolution_stage(state=state, extractor_client=extractor_client)
    return state.field_decisions[field.field_name]


def build_field_decision_from_final_action(
    *,
    state: GraphState,
    field: FieldDefinition,
    action: FieldResolutionAction,
) -> FieldDecision:
    """把模型 terminal action 转成内部 `FieldDecision`。"""

    if action.action != "final_decision":
        raise ValueError("build_field_decision_from_final_action requires final_decision")
    if action.field_name != field.field_name:
        raise ValueError("final_decision field_name does not match current field")

    field_candidate_ids = {
        candidate.candidate_id
        for candidate in state.candidates.get(field.field_name, [])
    }
    unknown_candidate_ids = [
        candidate_id
        for candidate_id in action.candidate_ids
        if candidate_id not in field_candidate_ids
    ]
    if unknown_candidate_ids:
        raise ValueError(f"unknown candidate_ids: {', '.join(unknown_candidate_ids)}")

    decision = FieldDecision(
        field_name=field.field_name,
        status=action.status or "failed",
        value=action.value,
        candidate_ids=list(action.candidate_ids),
        related_fields=list(action.related_fields),
        reason=action.reason,
        failure_reason=action.failure_reason,
    )
    record_action(
        state,
        field_name=field.field_name,
        action=ToolActionRecord(
            field_name=field.field_name,
            stage="resolution",
            action_type="final_decision",
            message=decision.reason or decision.failure_reason,
            candidate_ids=list(decision.candidate_ids),
            metadata={"status": decision.status},
        ),
    )
    return decision


def _pending_resolution_field_names(state: GraphState) -> list[str]:
    return [
        field.field_name
        for field in state.extraction_input.task_spec.fields
        if field.field_name not in state.field_decisions
    ]


def _ensure_known_field(*, state: GraphState, field_name: str) -> None:
    if field_name not in {
        field.field_name
        for field in state.extraction_input.task_spec.fields
    }:
        raise ValueError("resolution action field_name is not in task fields")


def _field_by_name(*, state: GraphState, field_name: str) -> FieldDefinition:
    for field in state.extraction_input.task_spec.fields:
        if field.field_name == field_name:
            return field
    raise ValueError("resolution action field_name is not in task fields")


def _record_tool_error(
    *,
    state: GraphState,
    field_name: str,
    tool_name: str,
    refs: list[str],
    error: Exception,
) -> dict[str, Any]:
    message = str(error)
    record_action(
        state,
        field_name=field_name,
        action=ToolActionRecord(
            field_name=field_name,
            stage="resolution",
            action_type="tool_error",
            message=message,
            refs=refs,
            metadata={"tool": tool_name},
        ),
    )
    return {
        "type": "tool_error",
        "tool": tool_name,
        "field_name": field_name,
        "error": message,
        "refs": refs,
        "instruction": "只能使用 search_grep 返回过的 ref；请重新调用工具并改用合法 ref。",
    }


def _shared_iteration_limit(*, state: GraphState, option_name: str) -> int:
    field_count = max(1, len(state.extraction_input.task_spec.fields))
    return getattr(state.extraction_input.options, option_name) * field_count


def _invoke_client(*, extractor_client: Any, output_schema: Any, messages: Any, tools: Any) -> Any:
    try:
        return extractor_client.invoke(
            output_schema=output_schema,
            messages=messages,
            tools=tools,
        )
    except TypeError as exc:
        if "tools" not in str(exc):
            raise
        return extractor_client.invoke(output_schema=output_schema, messages=messages)
