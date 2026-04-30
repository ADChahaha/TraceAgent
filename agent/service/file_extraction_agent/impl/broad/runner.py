"""broad 阶段 runner。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.broad.prompts import build_broad_messages
from service.file_extraction_agent.impl.schemas import (
    BroadAction,
    BroadFinishRecord,
    ToolActionRecord,
)
from service.file_extraction_agent.impl.state import GraphState, record_action
from service.file_extraction_agent.impl.tools.candidates import (
    add_broad_candidate,
    copy_field_candidates,
)
from service.file_extraction_agent.impl.tools.search import search_grep
from service.file_extraction_agent.schemas import FieldDefinition


BROAD_TOOLS = ["search_grep", "add_broad_candidate", "copy_field_candidates"]


def run_broad_stage(*, state: GraphState, extractor_client: Any) -> GraphState:
    """运行共享 broad loop，直到所有字段都返回 finish_broad。"""

    tool_results: list[Any] = []
    for _ in range(_shared_iteration_limit(state=state, option_name="max_broad_iterations")):
        pending_field_names = _pending_broad_field_names(state)
        if not pending_field_names:
            return state

        action = _invoke_client(
            extractor_client=extractor_client,
            output_schema=BroadAction,
            messages=build_broad_messages(
                state=state,
                tool_results=tool_results,
            ),
            tools=BROAD_TOOLS,
        )
        _ensure_known_field(state=state, field_name=action.field_name)

        if action.field_name in state.broad_finishes:
            raise ValueError("broad action field_name already finished")

        if action.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            tool_results = search_grep(
                state=state,
                field_name=action.field_name,
                query=action.query or "",
            )
            continue
        if action.action == "add_broad_candidate":
            try:
                tool_results = add_broad_candidate(
                    state=state,
                    field_name=action.field_name,
                    refs=list(action.refs),
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
        if action.action == "copy_field_candidates":
            _ensure_known_field(state=state, field_name=action.source_field_name or "")
            tool_results = copy_field_candidates(
                state=state,
                source_field_name=action.source_field_name or "",
                target_field_name=action.field_name,
                stage="broad",
                reason=action.reason or "",
            )
            continue

        _finish_broad(state=state, action=action)

    pending = ", ".join(_pending_broad_field_names(state))
    raise ValueError(
        "broad model did not finish all fields before iteration limit"
        f"; pending fields: {pending}"
    )


def run_broad_loop_for_field(
    *,
    state: GraphState,
    field: FieldDefinition,
    extractor_client: Any,
) -> BroadFinishRecord:
    """兼容旧内部调用：运行共享 broad loop 后返回指定字段 finish 记录。"""

    run_broad_stage(state=state, extractor_client=extractor_client)
    return state.broad_finishes[field.field_name]


def _finish_broad(*, state: GraphState, action: BroadAction) -> BroadFinishRecord:
    finish = BroadFinishRecord(
        field_name=action.field_name,
        status=action.status or "no_evidence",
        reason=action.reason or "",
    )
    if finish.status == "enough_evidence" and not state.candidates.get(action.field_name):
        raise ValueError("finish_broad status=enough_evidence requires candidates")
    state.broad_finishes[action.field_name] = finish
    record_action(
        state,
        field_name=action.field_name,
        action=ToolActionRecord(
            field_name=action.field_name,
            stage="broad",
            action_type="finish_broad",
            message=finish.reason,
            candidate_ids=[
                candidate.candidate_id
                for candidate in state.candidates.get(action.field_name, [])
            ],
            metadata={"status": finish.status},
        ),
    )
    return finish


def _pending_broad_field_names(state: GraphState) -> list[str]:
    return [
        field.field_name
        for field in state.extraction_input.task_spec.fields
        if field.field_name not in state.broad_finishes
    ]


def _ensure_known_field(*, state: GraphState, field_name: str) -> None:
    if field_name not in {
        field.field_name
        for field in state.extraction_input.task_spec.fields
    }:
        raise ValueError("broad action field_name is not in task fields")


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
            stage="broad",
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
