from __future__ import annotations

from typing import Any

from backend.crud.json_utils import loads_json


def serialize_field_agent_process(trace: dict[str, Any] | None) -> dict[str, Any] | None:
    if trace is None:
        return None
    return {
        "field_name": trace["field_name"],
        "status": trace["trace_status"],
        "evidence": loads_json(trace["evidence_json"], {}),
        "related_fields": loads_json(trace["related_fields_json"], []),
        "actions": loads_json(trace["actions_json"], []),
        "reason": trace["reason"],
        "failure_reason": trace["failure_reason"],
    }
