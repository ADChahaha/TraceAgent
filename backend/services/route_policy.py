from __future__ import annotations

from typing import Any

from backend.crud.json_utils import loads_json


def build_route_policy_request(
    *,
    task_spec: dict[str, Any],
    extracted_fields: list[dict[str, Any]],
    field_traces: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    trace_by_field = {trace["field_name"]: trace for trace in field_traces}
    field_outputs = [_build_field_output(field) for field in extracted_fields]
    refs_with_text = [
        _build_refs_with_text(field["field_name"], trace_by_field.get(field["field_name"]))
        for field in extracted_fields
    ]
    field_processes = [
        _build_field_process(field["field_name"], field, trace_by_field.get(field["field_name"]))
        for field in extracted_fields
    ]
    return {
        "task_spec": task_spec,
        "field_outputs": field_outputs,
        "refs_with_text": refs_with_text,
        "field_processes": field_processes,
        "metadata": metadata,
    }


def _build_field_output(field: dict[str, Any]) -> dict[str, Any]:
    output = {
        "field_name": field["field_name"],
        "status": field["agent_status"],
    }
    value = loads_json(field["agent_value_json"], None)
    if field["agent_status"] == "resolved":
        output["value"] = value
    return output


def _build_refs_with_text(
    field_name: str,
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    if trace is None:
        return {"field_name": field_name, "refs": []}

    evidence = loads_json(trace["evidence_json"], {})
    refs = evidence.get("refs") or []
    texts = evidence.get("texts") or []
    refs_with_text: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        item = dict(ref)
        item["text"] = texts[index] if index < len(texts) else ""
        refs_with_text.append(item)
    return {"field_name": field_name, "refs": refs_with_text}


def _build_field_process(
    field_name: str,
    field: dict[str, Any],
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    actions = loads_json(trace["actions_json"], []) if trace else []
    broad_actions = [
        action
        for action in actions
        if _action_stage(action) == "broad"
    ]
    resolution_actions = [
        action
        for action in actions
        if _action_stage(action) == "resolution"
    ]
    return {
        "field_name": field_name,
        "broad_extraction": {
            "status": _broad_status(trace, broad_actions),
            "search_queries": _search_queries(broad_actions),
            "candidate_action_count": _candidate_action_count(
                broad_actions,
                action_types={"add_broad_candidate", "copy_field_candidates"},
            ),
            "counted_fields": _counted_fields(broad_actions),
            "finish_reason": _finish_reason(broad_actions),
        },
        "field_resolution": {
            "status": field["agent_status"],
            "search_queries": _search_queries(resolution_actions),
            "candidate_action_count": _candidate_action_count(
                resolution_actions,
                action_type="add_resolution_candidate",
            ),
            "counted_fields": _counted_fields(resolution_actions),
            "final_decision_used": any(
                action.get("action_type") == "final_decision"
                for action in resolution_actions
            ),
            "reason": trace["reason"] if trace else field["reason"],
            "failure_reason": trace["failure_reason"] if trace else field["failure_reason"],
        },
    }


def _action_stage(action: dict[str, Any]) -> str:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    stage = metadata.get("stage")
    if stage in {"broad", "resolution"}:
        return stage

    action_type = action.get("action_type")
    if action_type in {"add_broad_candidate", "copy_field_candidates", "finish_broad"}:
        return "broad"
    if action_type in {
        "get_candidate_bundle",
        "add_resolution_candidate",
        "count_field_candidates",
        "final_decision",
    }:
        return "resolution"
    return "broad"


def _broad_status(
    trace: dict[str, Any] | None,
    broad_actions: list[dict[str, Any]],
) -> str | None:
    for action in broad_actions:
        if action.get("action_type") != "finish_broad":
            continue
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        status = metadata.get("status")
        if isinstance(status, str) and status:
            return status
    if trace:
        evidence = loads_json(trace["evidence_json"], {})
        status = evidence.get("status")
        if isinstance(status, str) and status:
            return status
    return None


def _search_queries(actions: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for action in actions:
        if action.get("action_type") not in {
            "search",
            "search_grep",
            "search_text_grep",
            "search_table_rows_grep",
            "text_grep",
            "table_row_grep",
        }:
            continue
        query = _action_query(action)
        if query and query not in queries:
            queries.append(query)
    return queries


def _action_query(action: dict[str, Any]) -> str | None:
    for key in ("query", "message"):
        value = action.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    value = metadata.get("query")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _candidate_action_count(
    actions: list[dict[str, Any]],
    *,
    action_type: str | None = None,
    action_types: set[str] | None = None,
) -> int:
    expected_action_types = action_types or ({action_type} if action_type else set())
    return sum(
        1
        for action in actions
        if action.get("action_type") in expected_action_types
    )


def _counted_fields(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counted_fields: list[dict[str, Any]] = []
    for action in actions:
        if action.get("action_type") != "count_field_candidates":
            continue
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        field_name = metadata.get("counted_field_name")
        count = metadata.get("count")
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        if not isinstance(count, int):
            continue
        counted_fields.append({"field_name": field_name.strip(), "count": count})
    return counted_fields


def _finish_reason(actions: list[dict[str, Any]]) -> str | None:
    for action in actions:
        if action.get("action_type") != "finish_broad":
            continue
        message = action.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None
