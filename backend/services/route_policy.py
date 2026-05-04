from __future__ import annotations

from typing import Any

from backend.crud.json_utils import loads_json


def build_route_policy_request(
    *,
    task_spec: dict[str, Any],
    extracted_fields: list[dict[str, Any]],
    field_traces: list[dict[str, Any]],
    metadata: dict[str, Any],
    block_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trace_by_field = {trace["field_name"]: trace for trace in field_traces}
    field_outputs = [_build_field_output(field) for field in extracted_fields]
    refs_with_text = [
        _build_refs_with_text(
            field["field_name"],
            trace_by_field.get(field["field_name"]),
            block_lookup=block_lookup or {},
        )
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
    *,
    block_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if trace is None:
        return {"field_name": field_name, "refs": []}

    evidence = loads_json(trace["evidence_json"], {})
    refs = evidence.get("refs") or []
    if not refs:
        refs = [{"block_id": block_id} for block_id in evidence.get("block_ids") or [] if block_id]
    texts = evidence.get("texts") or []
    refs_with_text: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        item = dict(ref)
        item["text"] = _resolve_ref_text(
            ref=item,
            texts=texts,
            index=index,
            block_lookup=block_lookup,
        )
        source_block = block_lookup.get(str(item.get("block_id") or ""))
        if source_block:
            if not item.get("document_id"):
                item["document_id"] = source_block.get("document_id")
            if not item.get("page"):
                item["page"] = source_block.get("page_no") or source_block.get("page")
        refs_with_text.append(item)
    return {"field_name": field_name, "refs": refs_with_text}


def _resolve_ref_text(
    *,
    ref: dict[str, Any],
    texts: list[Any],
    index: int,
    block_lookup: dict[str, dict[str, Any]],
) -> str:
    if index < len(texts) and isinstance(texts[index], str) and texts[index].strip():
        return texts[index]
    block_id = ref.get("block_id")
    if isinstance(block_id, str):
        block = block_lookup.get(block_id)
        if block and isinstance(block.get("text"), str):
            return block["text"]
    return ""


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
                action_types={"add_broad_candidate", "copy_field_candidates", "table_extraction"},
            ),
            "counted_fields": _counted_fields(broad_actions),
            "finish_reason": _finish_reason(broad_actions),
            **_diagnostics_payload(broad_actions),
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
                _action_type(action) in {"final_decision", "set_field"}
                for action in resolution_actions
            ),
            "reason": trace["reason"] if trace else field["reason"],
            "failure_reason": trace["failure_reason"] if trace else field["failure_reason"],
            **_diagnostics_payload(resolution_actions),
        },
    }


def _action_stage(action: dict[str, Any]) -> str:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    stage = metadata.get("stage")
    if stage in {"broad", "resolution"}:
        return stage

    action_type = _action_type(action)
    if action_type in {"add_broad_candidate", "copy_field_candidates", "finish_broad"}:
        return "broad"
    if action_type in {
        "get_candidate_bundle",
        "add_resolution_candidate",
        "count_field_candidates",
        "final_decision",
        "set_field",
    }:
        return "resolution"
    return "broad"


def _broad_status(
    trace: dict[str, Any] | None,
    broad_actions: list[dict[str, Any]],
) -> str | None:
    for action in broad_actions:
        if _action_type(action) != "finish_broad":
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
        action_type = _action_type(action)
        if action_type not in {
            "search",
            "search_grep",
            "search_text_grep",
            "search_table_rows_grep",
            "text_grep",
            "table_row_grep",
            "table_extraction",
        }:
            continue
        query = _action_query(action)
        if query and query not in queries:
            queries.append(query)
    return queries


def _action_query(action: dict[str, Any]) -> str | None:
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    for key in ("query", "sql", "reason"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("query", "message"):
        value = action.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    value = metadata.get("query")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _action_type(action: dict[str, Any]) -> str | None:
    action_type = action.get("action_type")
    if isinstance(action_type, str) and action_type.strip():
        return action_type.strip()
    tool_name = action.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        return tool_name.strip()
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
        if _action_type(action) in expected_action_types
    )


def _counted_fields(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counted_fields: list[dict[str, Any]] = []
    for action in actions:
        if _action_type(action) != "count_field_candidates":
            continue
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        field_name = metadata.get("counted_field_name")
        count = metadata.get("count")
        if not isinstance(field_name, str) or not field_name.strip():
            field_name = args.get("field_name") or args.get("source_field_name")
        if not isinstance(count, int):
            count = args.get("count")
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        if not isinstance(count, int):
            continue
        counted_fields.append({"field_name": field_name.strip(), "count": count})
    return counted_fields


def _finish_reason(actions: list[dict[str, Any]]) -> str | None:
    for action in actions:
        if _action_type(action) != "finish_broad":
            continue
        message = action.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        reason = args.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
    return None


def _diagnostics_payload(actions: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = _diagnostics(actions)
    return {"diagnostics": diagnostics} if diagnostics else {}


def _diagnostics(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for action in actions:
        action_type = _action_type(action)
        if action_type != "table_extraction":
            continue
        result = action.get("result") if isinstance(action.get("result"), dict) else {}
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        table_id = _text_or_none(result.get("table_id")) or _text_or_none(args.get("table_id"))
        query = _text_or_none(args.get("sql")) or _text_or_none(args.get("query"))
        for audit_type in ("table_audit", "query_audit"):
            audit = result.get(audit_type) if isinstance(result.get(audit_type), dict) else None
            if not audit:
                continue
            summary = _audit_summary(
                source=action_type,
                audit_type=audit_type,
                audit=audit,
                table_id=table_id,
                query=query,
            )
            if summary is not None:
                items.append(summary)
    return items


def _audit_summary(
    *,
    source: str,
    audit_type: str,
    audit: dict[str, Any],
    table_id: str | None,
    query: str | None,
) -> dict[str, Any] | None:
    summary_text = _text_or_none(audit.get("summary"))
    if summary_text is None and audit_type == "table_audit":
        summary_text = _table_audit_summary(audit)
    if summary_text is None and audit_type == "query_audit":
        return None
    summary: dict[str, Any] = {
        "source": source,
        "quality_type": audit_type,
        "issues": [],
    }
    if summary_text:
        summary["summary"] = summary_text
    if table_id:
        summary["table_id"] = table_id
    if query:
        summary["query"] = query
    return summary


def _table_audit_summary(audit: dict[str, Any]) -> str | None:
    parts: list[str] = []
    row_count = audit.get("row_count")
    column_count = audit.get("column_count")
    if isinstance(row_count, int):
        parts.append(f"表格 {row_count} 行")
    if isinstance(column_count, int):
        parts.append(f"{column_count} 列")

    blank_cells = audit.get("blank_cells") if isinstance(audit.get("blank_cells"), dict) else {}
    by_column = blank_cells.get("by_column") if isinstance(blank_cells.get("by_column"), list) else []
    blank_parts: list[str] = []
    for item in by_column[:5]:
        if not isinstance(item, dict):
            continue
        column = _text_or_none(item.get("column"))
        blank_count = item.get("blank_count")
        if column and isinstance(blank_count, int) and blank_count > 0:
            blank_parts.append(f"{column} 空白 {blank_count} 行")
    if blank_parts:
        parts.append("空白单元格：" + "，".join(blank_parts))

    structure_signals = audit.get("structure_signals")
    if isinstance(structure_signals, list) and structure_signals:
        codes = [
            code
            for signal in structure_signals[:5]
            if isinstance(signal, dict)
            for code in [_text_or_none(signal.get("code"))]
            if code
        ]
        if codes:
            parts.append("结构信号：" + "，".join(codes))

    if not parts:
        return None
    return "；".join(parts) + "。"


def _text_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
