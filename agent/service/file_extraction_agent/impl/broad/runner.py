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
from service.file_extraction_agent.impl.tools.candidates import add_broad_candidate
from service.file_extraction_agent.impl.tools.search import search_grep
from service.file_extraction_agent.schemas import FieldDefinition


BROAD_TOOLS = ["search_grep", "add_broad_candidate"]


def run_broad_stage(*, state: GraphState, extractor_client: Any) -> GraphState:
    """运行所有字段的 broad loop。"""

    for field in state.extraction_input.task_spec.fields:
        run_broad_loop_for_field(
            state=state,
            field=field,
            extractor_client=extractor_client,
        )
    return state


def run_broad_loop_for_field(
    *,
    state: GraphState,
    field: FieldDefinition,
    extractor_client: Any,
) -> BroadFinishRecord:
    """运行单字段 broad agent loop。"""

    tool_results: list[Any] = []
    for _ in range(state.extraction_input.options.max_broad_iterations):
        action = _invoke_client(
            extractor_client=extractor_client,
            output_schema=BroadAction,
            messages=build_broad_messages(
                state=state,
                field=field,
                tool_results=tool_results,
            ),
            tools=BROAD_TOOLS,
        )
        if action.field_name != field.field_name:
            raise ValueError("broad action field_name does not match current field")

        if action.action in {"search_grep", "search_text_grep", "search_table_rows_grep"}:
            tool_results = search_grep(
                state=state,
                field_name=field.field_name,
                query=action.query or "",
            )
            continue
        if action.action == "add_broad_candidate":
            tool_results = add_broad_candidate(
                state=state,
                field_name=field.field_name,
                refs=list(action.refs),
                reason=action.reason or "",
            )
            continue

        finish = BroadFinishRecord(
            field_name=field.field_name,
            status=action.status or "no_evidence",
            reason=action.reason or "",
        )
        if finish.status == "enough_evidence" and not state.candidates.get(field.field_name):
            raise ValueError("finish_broad status=enough_evidence requires candidates")
        state.broad_finishes[field.field_name] = finish
        record_action(
            state,
            field_name=field.field_name,
            action=ToolActionRecord(
                field_name=field.field_name,
                stage="broad",
                action_type="finish_broad",
                message=finish.reason,
                candidate_ids=[
                    candidate.candidate_id
                    for candidate in state.candidates.get(field.field_name, [])
                ],
                metadata={"status": finish.status},
            ),
        )
        return finish

    raise ValueError("broad model did not return finish_broad before iteration limit")


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
