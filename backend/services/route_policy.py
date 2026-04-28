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
    return {
        "task_spec": task_spec,
        "field_outputs": field_outputs,
        "refs_with_text": refs_with_text,
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

