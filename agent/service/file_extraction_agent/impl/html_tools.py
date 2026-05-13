"""Model-facing tools for virtual-tree file extraction."""

from __future__ import annotations

from typing import Any

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function


def build_tools(state: Any) -> list[Any]:
    """Build model-facing tools bound to the current graph state."""

    @tool
    def tree(path: str = "/", depth: int = 3, reason: str = "") -> dict[str, Any]:
        """Expand the virtual semantic HTML file tree at path."""

        return _tree(state, path, depth=depth, reason=reason)

    @tool
    def read(path: str, offset: int = 0, limit: int = 30, reason: str = "") -> dict[str, Any]:
        """Read a paragraph, list, or table virtual file as Markdown/text."""

        return _read(state, path, offset=offset, limit=limit, reason=reason)

    @tool
    def anchors(path: str, reason: str = "") -> dict[str, Any]:
        """Return Sxxx sentence ids for a paragraph .md virtual file."""

        return _anchors(state, path, reason=reason)

    @tool
    def query_table(path: str, sql: str, offset: int = 0, limit: int = 30, reason: str = "") -> dict[str, Any]:
        """Run a safe SELECT over a .table virtual file and return Markdown rows."""

        return _query_table(state, path, sql, offset=offset, limit=limit, reason=reason)

    @tool
    def bind_evidence(field_id: str, evidence: list[dict[str, Any]], reason: str = "") -> dict[str, Any]:
        """Bind evidence selectors to one schema field without submitting its value."""

        return _bind_evidence(state, field_id, evidence, reason=reason)

    @tool
    def review_field(field_id: str, reason: str = "") -> dict[str, Any]:
        """Return one field's description, current value, and bound evidence texts for reassessment."""

        return _review_field(state, field_id, reason=reason)

    @tool
    def write_field(
        field_id: str,
        value: Any,
        final_evidence: list[dict[str, Any]] | None = None,
        status: str = "resolved",
        reason: str = "",
    ) -> dict[str, Any]:
        """Write or overwrite one schema field value with reviewed final evidence."""

        return _write_field(state, field_id, value, final_evidence=final_evidence, status=status, reason=reason)

    @tool
    def submit_result(reason: str = "") -> dict[str, Any]:
        """Validate the current result buffer and submit the final extraction result."""

        return _submit_result(state, reason=reason)

    return [tree, read, anchors, query_table, bind_evidence, review_field, write_field, submit_result]


def _tree(state: Any, path: str = "/", *, depth: int = 3, reason: str = "") -> dict[str, Any]:
    return _run_tool(
        state,
        "tree",
        {"path": path, "depth": depth},
        reason,
        lambda: _tree_result(state, path, depth),
    )


def _read(
    state: Any,
    path: str,
    *,
    offset: int = 0,
    limit: int = 30,
    reason: str = "",
) -> dict[str, Any]:
    return _run_tool(
        state,
        "read",
        {"path": path, "offset": offset, "limit": limit},
        reason,
        lambda: {"ok": True, **state.document.read_markdown(path, offset=offset, limit=limit)},
    )


def _anchors(state: Any, path: str, *, reason: str = "") -> dict[str, Any]:
    return _run_tool(
        state,
        "anchors",
        {"path": path},
        reason,
        lambda: {
            "ok": True,
            "path": state.document.resolve_path(path),
            "anchors": state.document.paragraph_anchors(path),
        },
    )


def _query_table(
    state: Any,
    path: str,
    sql: str,
    *,
    offset: int = 0,
    limit: int = 30,
    reason: str = "",
) -> dict[str, Any]:
    return _run_tool(
        state,
        "query_table",
        {"path": path, "sql": sql, "offset": offset, "limit": limit},
        reason,
        lambda: {"ok": True, **state.document.query_table(path, sql, offset=offset, limit=limit)},
    )


def _bind_evidence(
    state: Any,
    field_id: str,
    evidence: list[dict[str, Any]] | None,
    *,
    reason: str = "",
) -> dict[str, Any]:
    evidence = evidence or []

    def execute() -> dict[str, Any]:
        field = field_definition(state, field_id)
        if field is None:
            return {"ok": False, "errors": [{"field_id": field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"}]}
        errors = [{"field_id": field_id, **error} for error in state.document.validate_evidence(evidence)]
        if errors:
            return {"ok": False, "errors": errors}
        canonical_evidence = state.document.canonicalize_evidence(evidence)
        existing = state.evidence_states.get(field_id, {})
        combined = [*(existing.get("evidence") or []), *canonical_evidence]
        evidence_texts = state.document.evidence_texts(combined)
        state.evidence_states[field_id] = {
            "field_id": field_id,
            "evidence": combined,
            "evidence_texts": evidence_texts,
            "reason": reason,
        }
        state.review_states.pop(field_id, None)
        return {
            "ok": True,
            "field_id": field_id,
            "evidence": combined,
            "evidence_texts": evidence_texts,
        }

    result = _run_tool(
        state,
        "bind_evidence",
        {"field_id": field_id, "evidence": evidence},
        reason,
        execute,
    )
    if result.get("ok") is True:
        _emit_event(
            state,
            {
                "type": "evidence_bound",
                "tool": "bind_evidence",
                "reason": reason,
                "field_id": field_id,
                "evidence": result["evidence"],
                "evidence_texts": result["evidence_texts"],
            },
        )
    return result


def _write_field(
    state: Any,
    field_id: str,
    value: Any,
    *,
    final_evidence: list[dict[str, Any]] | None = None,
    status: str = "resolved",
    reason: str = "",
) -> dict[str, Any]:
    final_evidence = final_evidence or []

    def execute() -> dict[str, Any]:
        evidence_state = state.evidence_states.get(field_id, {})
        candidate_evidence = evidence_state.get("evidence") or []
        canonical_final_evidence = state.document.canonicalize_evidence(final_evidence)
        errors = validate_field_write(state, field_id, value, status)
        errors.extend(validate_final_evidence_write(state, field_id, candidate_evidence, canonical_final_evidence))
        if errors:
            return {"ok": False, "errors": errors}
        evidence_texts = state.document.evidence_texts(canonical_final_evidence)
        field = {
            "field_id": field_id,
            "status": status,
            "value": value,
            "evidence": canonical_final_evidence,
            "evidence_texts": evidence_texts,
            "reason": reason,
        }
        state.field_states[field_id] = field
        return {"ok": True, "field": field}

    result = _run_tool(
        state,
        "write_field",
        {"field_id": field_id, "value": value, "final_evidence": final_evidence, "status": status},
        reason,
        execute,
    )
    if result.get("ok") is True:
        _emit_event(
            state,
            {
                "type": "field_written",
                "tool": "write_field",
                "reason": reason,
                "field": result["field"],
            },
        )
    return result


def _review_field(state: Any, field_id: str, *, reason: str = "") -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        field = field_definition(state, field_id)
        if field is None:
            return {"ok": False, "errors": [{"field_id": field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"}]}
        evidence_state = state.evidence_states.get(field_id, {})
        field_state = state.field_states.get(field_id, {})
        evidence = evidence_state.get("evidence") or field_state.get("evidence") or []
        evidence_texts = evidence_state.get("evidence_texts") or field_state.get("evidence_texts")
        if evidence_texts is None:
            evidence_texts = state.document.evidence_texts(evidence)
        state.review_states[field_id] = {
            "field_id": field_id,
            "evidence": evidence,
            "evidence_units": sorted(_selector_units(evidence)),
            "reason": reason,
        }
        return {
            "ok": True,
            "field_id": field_id,
            "field_description": getattr(field, "description", "") or "",
            "field": field_state or None,
            "evidence": evidence,
            "evidence_texts": evidence_texts,
            "guidance": (
                "This tool does not judge correctness. Re-read the field description, current value, "
                "and bound evidence, then decide whether to keep the value, overwrite it with write_field, "
                "or bind additional evidence."
            ),
        }

    return _run_tool(
        state,
        "review_field",
        {"field_id": field_id},
        reason,
        execute,
    )


def _submit_result(state: Any, *, reason: str = "") -> dict[str, Any]:
    result = _run_tool(
        state,
        "submit_result",
        {},
        reason,
        lambda: validate_and_build_result(state),
        emit_result_completed=False,
    )
    if result.get("ok") is True:
        trace = {**result["trace"], "events": list(result["trace"].get("events", []))}
        _emit_event(
            state,
            {
                "type": "result_completed",
                "tool": "submit_result",
                "reason": reason,
                "result": result["result"],
                "trace": trace,
            },
        )
    return result


def _tree_result(state: Any, path: str, depth: int) -> dict[str, Any]:
    canonical_path = state.document.resolve_path(path)
    return {
        "ok": True,
        "path": canonical_path,
        "depth": depth,
        "text": state.document.tree_text(canonical_path, depth=depth),
    }


def validate_field_write(
    state: Any,
    field_id: str,
    value: Any,
    status: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    field = field_definition(state, field_id)
    if field is None:
        return [{"field_id": field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"}]
    if status not in {"resolved", "missing"}:
        errors.append({"field_id": field_id, "code": "BAD_STATUS", "message": "status must be resolved or missing"})
    if status == "resolved":
        type_error = validate_value_type(field, value)
        if type_error:
            errors.append({"field_id": field_id, "code": "TYPE_MISMATCH", "message": type_error, "current_value": value})
    return errors


def validate_final_evidence_write(
    state: Any,
    field_id: str,
    candidate_evidence: list[dict[str, Any]],
    final_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    candidate_units = _selector_units(candidate_evidence)
    final_units = _selector_units(final_evidence)
    if final_evidence:
        errors.extend({"field_id": field_id, **error} for error in state.document.validate_evidence(final_evidence))
    if errors:
        return errors
    if candidate_units:
        review_state = state.review_states.get(field_id)
        reviewed_units = set(tuple(item) for item in review_state.get("evidence_units", [])) if review_state else set()
        if reviewed_units != candidate_units:
            return [
                {
                    "field_id": field_id,
                    "code": "REVIEW_REQUIRED",
                    "message": "bound candidate evidence must be reviewed before write_field",
                }
            ]
    if final_units and not final_units.issubset(candidate_units):
        errors.append(
            {
                "field_id": field_id,
                "code": "UNBOUND_FINAL_EVIDENCE",
                "message": "final_evidence must be selected from evidence already bound to this field",
            }
        )
    return errors


def validate_and_build_result(state: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for field in state.task_spec.fields:
        field_state = state.field_states.get(field.name)
        if field_state is None:
            errors.append({"field_id": field.name, "code": "MISSING_FIELD", "message": "field was not written"})
            continue
        if field.required and field_state.get("status") != "resolved":
            errors.append({"field_id": field.name, "code": "REQUIRED_MISSING", "message": "required field is not resolved"})
            continue
        if field_state.get("status") == "resolved" and not empty_evidence_allowed(field, field_state.get("value")):
            if not _selector_units(field_state.get("evidence") or []):
                errors.append(
                    {
                        "field_id": field.name,
                        "code": "MISSING_FINAL_EVIDENCE",
                        "message": "resolved non-null field must include final evidence",
                    }
                )
    if errors:
        return {"ok": False, "errors": errors}
    fields = [_field_with_evidence_texts(state, state.field_states[field.name]) for field in state.task_spec.fields if field.name in state.field_states]
    result = {"fields": fields}
    trace = {"events": list(state.events), "actions": list(state.actions), "document_tree": state.document.tree_text("/", depth=3)}
    return {"ok": True, "result": result, "trace": trace}


def field_definition(state: Any, field_id: str) -> Any:
    for field in state.task_spec.fields:
        if field.name == field_id:
            return field
    return None


def _field_with_evidence_texts(state: Any, field_state: dict[str, Any]) -> dict[str, Any]:
    if "evidence_texts" in field_state:
        return field_state
    return {
        **field_state,
        "evidence_texts": state.document.evidence_texts(field_state.get("evidence") or []),
    }


def validate_value_type(field: Any, value: Any) -> str | None:
    field_type = getattr(field, "type", "string")
    if field_type == "string":
        return None if isinstance(value, str) else "expected string"
    if field_type == "number":
        return None if isinstance(value, (int, float)) and not isinstance(value, bool) else "expected number"
    if field_type == "boolean":
        return None if isinstance(value, bool) else "expected boolean"
    if field_type == "list[string]":
        return None if isinstance(value, list) and all(isinstance(item, str) for item in value) else "expected list[string]"
    if field_type == "list[number]":
        return None if isinstance(value, list) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value) else "expected list[number]"
    if field_type == "null":
        return None if value is None else "expected null"
    if field_type == "enum":
        return validate_enum_value(field, value)
    return None


def validate_enum_value(field: Any, value: Any) -> str | None:
    if not isinstance(value, dict):
        return "expected enum object"
    variant_name = value.get("variant")
    variants = {variant.name: variant for variant in getattr(field, "variants", []) or []}
    variant = variants.get(variant_name)
    if variant is None:
        return "unknown enum variant"
    fake_field = type("Field", (), {"type": variant.type})()
    return validate_value_type(fake_field, value.get("value"))


def empty_evidence_allowed(field: Any, value: Any) -> bool:
    field_type = getattr(field, "type", "string")
    if field_type == "null":
        return True
    if field_type != "enum" or not isinstance(value, dict):
        return False
    variant_name = value.get("variant")
    variants = {variant.name: variant for variant in getattr(field, "variants", []) or []}
    variant = variants.get(variant_name)
    return getattr(variant, "type", None) == "null"


def _selector_units(evidence: list[dict[str, Any]] | None) -> set[tuple[str, str, str]]:
    units: set[tuple[str, str, str]] = set()
    for selector in evidence or []:
        path = selector.get("path")
        if not isinstance(path, str):
            continue
        for key in ("sentences", "items", "rows"):
            values = selector.get(key)
            if isinstance(values, list):
                units.update((path, key, str(value)) for value in values)
    return units


def _run_tool(
    state: Any,
    tool_name: str,
    args: dict[str, Any],
    reason: str,
    execute,
    *,
    emit_result_completed: bool = True,
) -> dict[str, Any]:
    _emit_event(
        state,
        {
            "type": "tool_started",
            "tool": tool_name,
            "reason": reason,
            "args": args,
        },
    )
    try:
        result = execute()
    except Exception as exc:  # pragma: no cover - exercised by tool users
        result = {"ok": False, "errors": [{"message": str(exc)}]}
    event_type = "tool_completed" if result.get("ok") is not False else "tool_failed"
    event_result = result
    if tool_name == "submit_result" and result.get("ok") is True:
        event_result = {"ok": True, "result": result.get("result")}
    _record_action(state, tool_name, args, reason, event_result)
    _emit_event(
        state,
        {
            "type": event_type,
            "tool": tool_name,
            "reason": reason,
            "args": args,
            "result": event_result,
        },
    )
    return result


def _record_action(state: Any, tool_name: str, args: dict[str, Any], reason: str, result: dict[str, Any]) -> None:
    state.actions.append(
        {
            "tool_name": tool_name,
            "args": args,
            "reason": reason,
            "result": result,
        }
    )


def _emit_event(state: Any, payload: dict[str, Any]) -> None:
    event = {"seq": state.next_seq, **payload}
    state.next_seq += 1
    state.events.append(event)


__all__ = [
    "build_tools",
    "_tree",
    "_read",
    "_anchors",
    "_query_table",
    "_bind_evidence",
    "_review_field",
    "_write_field",
    "_submit_result",
]
