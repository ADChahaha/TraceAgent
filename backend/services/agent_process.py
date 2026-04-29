from __future__ import annotations

from typing import Any

from backend.crud.json_utils import loads_json


_MISSING = object()


def serialize_field_agent_process(
    trace: dict[str, Any] | None,
    *,
    value: Any = _MISSING,
) -> dict[str, Any] | None:
    if trace is None:
        return None
    return build_field_agent_process(
        field_name=trace["field_name"],
        status=trace["trace_status"],
        evidence=loads_json(trace["evidence_json"], {}),
        related_fields=loads_json(trace["related_fields_json"], []),
        actions=loads_json(trace["actions_json"], []),
        reason=trace["reason"],
        failure_reason=trace["failure_reason"],
        value=value,
    )


def build_field_agent_process(
    *,
    field_name: str | None,
    status: str | None,
    evidence: dict[str, Any],
    related_fields: list[str],
    actions: list[dict[str, Any]],
    reason: str | None,
    failure_reason: str | None,
    value: Any = _MISSING,
) -> dict[str, Any]:
    process = {
        "field_name": field_name,
        "status": status,
        "evidence": evidence,
        "related_fields": related_fields,
        "actions": actions,
        "reason": reason,
        "failure_reason": failure_reason,
        "process_steps": build_field_process_steps(
            status=status,
            evidence=evidence,
            related_fields=related_fields,
            actions=actions,
            reason=reason,
            failure_reason=failure_reason,
            value=value,
        ),
    }
    if value is not _MISSING:
        process["value"] = value
    return process


def build_field_process_steps(
    *,
    status: str | None,
    evidence: dict[str, Any],
    related_fields: list[str],
    actions: list[dict[str, Any]],
    reason: str | None,
    failure_reason: str | None,
    value: Any = _MISSING,
) -> list[dict[str, Any]]:
    final_step: dict[str, Any] = {
        "stage": "final_result",
        "title": "第三步 final result",
        "status": status,
        "reason": reason,
        "failure_reason": failure_reason,
    }
    if value is not _MISSING:
        final_step["value"] = value

    return [
        {
            "stage": "broad_extraction",
            "title": "第一步 broad extraction",
            "status": evidence.get("status") or status,
            "evidence": evidence,
        },
        {
            "stage": "field_resolution",
            "title": "第二步 resolution / tool",
            "status": "used" if actions else "skipped",
            "related_fields": related_fields,
            "actions": actions,
        },
        final_step,
    ]
