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
    get_candidate_bundle,
)
from service.file_extraction_agent.impl.tools.search import search_grep
from service.file_extraction_agent.schemas import FieldDefinition


RESOLUTION_TOOLS = [
    "get_candidate_bundle",
    "search_grep",
    "add_resolution_candidate",
]


def run_resolution_stage(*, state: GraphState, extractor_client: Any) -> GraphState:
    """运行所有字段的 resolution loop。"""

    for field in state.extraction_input.task_spec.fields:
        decision = run_resolution_loop_for_field(
            state=state,
            field=field,
            extractor_client=extractor_client,
        )
        state.field_decisions[field.field_name] = decision
    return state


def run_resolution_loop_for_field(
    *,
    state: GraphState,
    field: FieldDefinition,
    extractor_client: Any,
) -> FieldDecision:
    """运行单字段 resolution agent loop。"""

    tool_results: list[Any] = []
    for _ in range(state.extraction_input.options.max_resolution_iterations):
        action = _invoke_client(
            extractor_client=extractor_client,
            output_schema=FieldResolutionAction,
            messages=build_resolution_messages(
                state=state,
                field=field,
                tool_results=tool_results,
            ),
            tools=RESOLUTION_TOOLS,
        )
        if action.field_name != field.field_name:
            raise ValueError("resolution action field_name does not match current field")

        if action.action == "get_candidate_bundle":
            tool_results = get_candidate_bundle(state=state, field_name=field.field_name)
            continue
        if action.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            tool_results = search_grep(
                state=state,
                field_name=field.field_name,
                query=action.query or "",
                stage="resolution",
            )
            continue
        if action.action == "add_resolution_candidate":
            tool_results = add_resolution_candidate(
                state=state,
                field_name=field.field_name,
                refs=list(action.refs),
                reason=action.reason or "",
            )
            continue

        decision = build_field_decision_from_final_action(
            state=state,
            field=field,
            action=action,
        )
        state.field_decisions[field.field_name] = decision
        return decision

    raise ValueError("resolution model did not return final_decision before iteration limit")


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
