"""Model-facing tools for virtual-tree file extraction."""

from __future__ import annotations

import re
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
    def tree(path_id: str = "[0000]", depth: int = 3, reason: str = "") -> dict[str, Any]:
        """Expand the virtual semantic HTML file tree at a directory path_id.

        Use this for directories: root, document directories, and section directories.
        Use only path_id values such as [0000.0001] copied from tree output. Directory
        names are shown with a trailing slash in tree output. tree returns child
        directories and readable .md/.list/.table file path_ids; it does not return file
        text. If you need content inside a directory, call tree on that directory first,
        then call read on one of the child file path_ids ending in .md, .list, or .table.
        """

        return _tree(state, path_id, depth=depth, reason=reason)

    @tool
    def read(path_id: str, offset: int = 0, limit: int = 0, reason: str = "") -> dict[str, Any]:
        """Only read file path_ids ending in .md, .list, or .table in tree output.

        Use only path_id values such as [0000.0001.0002] copied from tree output. Never
        call read on document or section directories. If tree shows a directory ending
        with /, call tree on that directory first, then read a child .md/.list/.table file
        path_id.
        Paragraph .md files return plain text without sentence ids. List and table reads
        return Markdown with Ixxx item ids or Rxxx row ids. By default list/table reads
        return the whole object; use offset/limit only for intentional pagination.
        After a successful read, the next tool must be bind_evidence or skip_read.
        Use bind_evidence if the current read object may support, contradict, or qualify
        any schema field. Use skip_read only when the current read object is irrelevant
        to every field.
        """

        return _read(state, path_id, offset=offset, limit=limit, reason=reason)

    @tool
    def bind_evidence(
        field_id: str = "",
        bindings: list[dict[str, Any]] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Bind the current read object as block candidate evidence for one field.

        Only call this immediately after a successful read, before any non-bind tool.
        bind_evidence uses the current read object. Do not pass path_id, sentences, items, or rows.
        The candidate evidence stored by this tool is block-level {path_id}; call
        review_evidences later to expand block candidate evidence into Sxxx/Ixxx/Rxxx
        inline selectors for final_evidence. Use bindings=[{field_id}, ...] when the current read object supports multiple fields.
        """

        return _bind_evidence(state, field_id, bindings=bindings, reason=reason)

    @tool
    def skip_read(reason: str = "") -> dict[str, Any]:
        """Mark the current read object as irrelevant and close the read judgement.

        Use this only when the current read object is irrelevant to every schema field.
        It writes no field value and no evidence; it only lets the agent continue after
        explicitly judging the latest read.
        """

        return _skip_read(state, reason=reason)

    @tool
    def review_evidences(field_id: str, reason: str = "") -> dict[str, Any]:
        """Review one field's block candidates and expose inline final-evidence selectors.

        review_evidences expands block candidate evidence into inline selectors:
        paragraph blocks become {path_id, sentences}, list blocks become {path_id, items}, and
        table blocks become {path_id, rows}. It also returns evidence_texts. Use these
        returned inline selectors as the only source for write_field(final_evidence=...).
        """

        return _review_evidences(state, field_id, reason=reason)

    @tool
    def write_field(
        field_id: str,
        value: Any,
        final_evidence: list[dict[str, Any]] | None = None,
        status: str = "resolved",
        reason: str = "",
    ) -> dict[str, Any]:
        """Write or overwrite one schema field value with selected final evidence.

        write_field must immediately follow review_evidences for the same field. If
        any other tool call happens after review_evidences, review that field again
        before writing. This also applies to status="missing" and null enum variants.
        final_evidence must be copied from review_evidences.evidence for the same field.
        Do not use block-level {path_id} selectors as final_evidence.
        Use status="resolved" for extracted values and status="missing" when the document
        does not support the field. Array fields must be written as a complete array; do
        not append items incrementally. Rewriting the same field replaces the prior value.
        """

        return _write_field(state, field_id, value, final_evidence=final_evidence, status=status, reason=reason)

    @tool
    def submit_result(reason: str = "") -> dict[str, Any]:
        """Validate the current result buffer and submit the final extraction result.

        submit_result checks required fields, value types, enum variants, and evidence.
        Only null-typed fields or null enum variants may use final_evidence=[]. Resolved
        non-null values and non-null enum variants require non-empty final_evidence. If
        submit_result returns errors, fix the indicated fields and submit again.
        """

        return _submit_result(state, reason=reason)

    return [tree, read, bind_evidence, skip_read, review_evidences, write_field, submit_result]


def _tree(state: Any, path_id: str = "[0000]", *, depth: int = 3, reason: str = "") -> dict[str, Any]:
    return _run_tool(
        state,
        "tree",
        {"path_id": path_id, "depth": depth},
        reason,
        lambda: _path_id_error(path_id) or _tree_result(state, path_id, depth),
    )


def _read(
    state: Any,
    path_id: str,
    *,
    offset: int = 0,
    limit: int = 0,
    reason: str = "",
) -> dict[str, Any]:
    return _run_tool(
        state,
        "read",
        {"path_id": path_id, "offset": offset, "limit": limit},
        reason,
        lambda: _path_id_error(path_id) or {"ok": True, **state.document.read_markdown(path_id, offset=offset, limit=limit)},
    )


def _anchors(state: Any, path: str, *, reason: str = "") -> dict[str, Any]:
    try:
        ordering_error = validate_inline_request_after_read(state, path)
    except ValueError as exc:
        ordering_error = {"code": "INLINE_REQUIRES_READ", "message": str(exc)}
    if ordering_error:
        return _run_tool(
            state,
            "anchors",
            {"path": path},
            reason,
            lambda: {"ok": False, "errors": [ordering_error]},
        )
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
    field_id: str = "",
    *,
    bindings: list[dict[str, Any]] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    normalized_bindings = normalize_evidence_bindings(field_id, bindings)

    def execute() -> dict[str, Any]:
        pending_read = state.pending_read or {}
        path_id = pending_read.get("path_id")
        kind = pending_read.get("kind")
        if not isinstance(path_id, str) or kind not in {"paragraph", "list", "table"}:
            return {"ok": False, "errors": [{"code": "READ_REQUIRED", "message": "bind_evidence requires the current pending read object"}]}
        errors: list[dict[str, Any]] = []
        for binding in normalized_bindings:
            binding_field_id = binding.get("field_id")
            if not isinstance(binding_field_id, str) or not binding_field_id:
                errors.append({"field_id": binding_field_id, "code": "BAD_BINDING", "message": "field_id is required"})
                continue
            if field_definition(state, binding_field_id) is None:
                errors.append({"field_id": binding_field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"})
        if errors:
            return {"ok": False, "errors": errors}

        canonical_evidence = [{"path_id": state.document.path_id(path_id)}]
        results: list[dict[str, Any]] = []
        for binding in normalized_bindings:
            binding_field_id = binding["field_id"]
            existing = state.evidence_states.get(binding_field_id, {})
            combined = [*(existing.get("evidence") or []), *canonical_evidence]
            state.evidence_states[binding_field_id] = {
                "field_id": binding_field_id,
                "evidence": combined,
                "reason": reason,
            }
            state.review_states.pop(binding_field_id, None)
            results.append(
                {
                    "field_id": binding_field_id,
                    "candidate_evidence": combined,
                }
            )
        return {
            "ok": True,
            "bindings": results,
            "current_read": pending_read,
        }

    result = _run_tool(
        state,
        "bind_evidence",
        {"field_id": field_id, "bindings": bindings},
        reason,
        execute,
    )
    if result.get("ok") is True:
        for binding in result["bindings"]:
            _emit_event(
                state,
                {
                    "type": "evidence_bound",
                    "tool": "bind_evidence",
                    "reason": reason,
                    "field_id": binding["field_id"],
                    "candidate_evidence": binding["candidate_evidence"],
                },
            )
        if len(result["bindings"]) == 1:
            result.update(result["bindings"][0])
    return result


def _skip_read(state: Any, *, reason: str = "") -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        pending_read = state.pending_read
        if not pending_read:
            return {"ok": False, "errors": [{"code": "READ_REQUIRED", "message": "skip_read requires the current pending read object"}]}
        return {"ok": True, "skipped": pending_read}

    return _run_tool(
        state,
        "skip_read",
        {},
        reason,
        execute,
    )


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
        immediate_review_error = validate_immediate_review_before_write(state, field_id)
        if immediate_review_error:
            return {"ok": False, "errors": [immediate_review_error]}
        canonical_final_evidence = state.document.canonicalize_evidence(final_evidence)
        errors = validate_field_write(state, field_id, value, status)
        errors.extend(validate_final_evidence_write(state, field_id, canonical_final_evidence, value, status))
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


def _review_evidences(state: Any, field_id: str, *, reason: str = "") -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        field = field_definition(state, field_id)
        if field is None:
            return {"ok": False, "errors": [{"field_id": field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"}]}
        evidence_state = state.evidence_states.get(field_id, {})
        field_state = state.field_states.get(field_id, {})
        candidate_evidence = evidence_state.get("evidence") or []
        evidence = expand_candidate_evidence(state, candidate_evidence)
        evidence_texts = state.document.evidence_texts(evidence)
        state.review_states[field_id] = {
            "field_id": field_id,
            "candidate_evidence": candidate_evidence,
            "evidence": evidence,
            "evidence_units": sorted(_selector_units(evidence)),
            "reason": reason,
        }
        return {
            "ok": True,
            "field_id": field_id,
            "field_description": getattr(field, "description", "") or "",
            "field": field_state or None,
            "candidate_evidence": candidate_evidence,
            "evidence": evidence,
            "evidence_texts": evidence_texts,
            "guidance": (
                "This tool does not judge correctness. Copy only useful inline selectors from "
                "review_evidences.evidence into write_field(final_evidence=...)."
            ),
        }

    return _run_tool(
        state,
        "review_evidences",
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


def _tree_result(state: Any, path_id: str, depth: int) -> dict[str, Any]:
    canonical_path_id = state.document.path_id(path_id)
    return {
        "ok": True,
        "path_id": canonical_path_id,
        "depth": depth,
        "text": state.document.tree_text(canonical_path_id, depth=depth),
    }


def _path_id_error(path_id: str) -> dict[str, Any] | None:
    if isinstance(path_id, str) and re.fullmatch(r"\[\d{4}(?:\.\d{4})*\]", path_id.strip()):
        return None
    return {
        "ok": False,
        "errors": [
            {
                "code": "BAD_PATH_ID",
                "message": "use a path_id like [0000.0001] copied from tree output; raw paths are not accepted",
            }
        ],
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
    final_evidence: list[dict[str, Any]],
    value: Any,
    status: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    field = field_definition(state, field_id)
    final_evidence = state.document.canonicalize_evidence(final_evidence)
    final_units = _selector_units(final_evidence)
    review_state = state.review_states.get(field_id)
    reviewed_units = set(tuple(item) for item in review_state.get("evidence_units", [])) if review_state else set()
    if final_evidence:
        block_selectors = [selector for selector in final_evidence if _is_block_selector(selector)]
        if block_selectors:
            return [
                {
                    "field_id": field_id,
                    "code": "INLINE_FINAL_EVIDENCE_REQUIRED",
                    "message": "final_evidence must use inline selectors from review_evidences, not block-level {path_id} selectors",
                }
            ]
    if final_units and not final_units.issubset(reviewed_units):
        errors.append(
            {
                "field_id": field_id,
                "code": "UNREVIEWED_FINAL_EVIDENCE",
                "message": "final_evidence must be selected from review_evidences.evidence for this field",
            }
        )
    if errors:
        return errors
    if final_evidence:
        errors.extend({"field_id": field_id, **error} for error in state.document.validate_evidence(final_evidence))
    return errors


def validate_immediate_review_before_write(state: Any, field_id: str) -> dict[str, Any] | None:
    if state.last_tool_name == "review_evidences" and state.last_review_field_id == field_id:
        return None
    return {
        "field_id": field_id,
        "code": "IMMEDIATE_REVIEW_REQUIRED",
        "message": "write_field must immediately follow review_evidences for the same field",
    }


def expand_candidate_evidence(state: Any, evidence: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for selector in evidence or []:
        if not isinstance(selector, dict):
            continue
        path_id = selector.get("path_id")
        if not isinstance(path_id, str):
            continue
        try:
            expanded.append(state.document.inline_selector_for_path(path_id))
        except ValueError:
            continue
    return expanded


def normalize_evidence_bindings(field_id: str, bindings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if bindings is None:
        return [{"field_id": field_id}]
    if not isinstance(bindings, list) or not bindings:
        return [{"field_id": ""}]
    normalized: list[dict[str, Any]] = []
    for binding in bindings:
        if isinstance(binding, dict):
            normalized.append({"field_id": binding.get("field_id", "")})
        else:
            normalized.append({"field_id": ""})
    return normalized


def validate_inline_request_after_read(state: Any, path: str) -> dict[str, Any] | None:
    canonical_path = state.document.resolve_path(path)
    last_read = state.last_read or {}
    if state.last_tool_name != "read" or last_read.get("path") != canonical_path or last_read.get("kind") != "paragraph":
        return {
            "code": "INLINE_REQUIRES_READ",
            "message": "anchors must be called immediately after read on the same paragraph .md path",
        }
    return None


def validate_evidence_from_latest_inline(state: Any, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_units = _selector_units(evidence)
    inline_source = state.last_inline_source or {}
    inline_units = set(tuple(item) for item in inline_source.get("evidence_units", []))
    if not evidence_units or not inline_units:
        return [
            {
                "code": "BIND_REQUIRES_INLINE",
                "message": "bind_evidence must immediately follow anchors, read, or query_table that exposed the referenced inline ids",
            }
        ]
    if not evidence_units.issubset(inline_units):
        return [
            {
                "code": "BIND_REQUIRES_INLINE",
                "message": "evidence selectors must come from the immediately preceding inline-producing tool result",
            }
        ]
    return []


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
        path_id = selector.get("path_id")
        if not isinstance(path_id, str):
            continue
        for key in ("sentences", "items", "rows"):
            values = selector.get(key)
            if isinstance(values, list):
                units.update((path_id, key, str(value)) for value in values)
    return units


def _is_block_selector(selector: dict[str, Any]) -> bool:
    return isinstance(selector.get("path_id"), str) and not any(key in selector for key in ("sentences", "items", "rows"))


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
    ordering_error = validate_tool_order(state, tool_name)
    if ordering_error:
        result = {"ok": False, "errors": [ordering_error]}
        _record_action(state, tool_name, args, reason, result)
        _emit_event(
            state,
            {
                "type": "tool_failed",
                "tool": tool_name,
                "reason": reason,
                "args": args,
                "result": result,
            },
        )
        return result
    try:
        result = execute()
    except Exception as exc:  # pragma: no cover - exercised by tool users
        result = {"ok": False, "errors": [{"message": str(exc)}]}
    event_type = "tool_completed" if result.get("ok") is not False else "tool_failed"
    event_result = result
    if tool_name == "submit_result" and result.get("ok") is True:
        event_result = {"ok": True, "result": result.get("result")}
    _record_action(state, tool_name, args, reason, event_result)
    _update_tool_cursor(state, tool_name, event_result)
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


def validate_tool_order(state: Any, tool_name: str) -> dict[str, Any] | None:
    if state.pending_read and tool_name not in {"bind_evidence", "skip_read"}:
        return {
            "code": "READ_JUDGEMENT_REQUIRED",
            "message": "after read, call bind_evidence or skip_read before any other tool",
            "pending_read": state.pending_read,
        }
    if tool_name in {"bind_evidence", "skip_read"} and not state.pending_read:
        return {
            "code": "READ_REQUIRED",
            "message": f"{tool_name} requires a current pending read object",
        }
    return None


def _record_action(state: Any, tool_name: str, args: dict[str, Any], reason: str, result: dict[str, Any]) -> None:
    state.actions.append(
        {
            "tool_name": tool_name,
            "args": args,
            "reason": reason,
            "result": result,
        }
    )


def _update_tool_cursor(state: Any, tool_name: str, result: dict[str, Any]) -> None:
    state.last_tool_name = tool_name
    if tool_name == "review_evidences" and result.get("ok") is False:
        state.last_review_field_id = None
        return
    if result.get("ok") is False:
        return
    if tool_name == "review_evidences":
        state.last_review_field_id = result.get("field_id")
        return
    if tool_name == "bind_evidence":
        state.pending_read = None
        return
    if tool_name == "read":
        state.last_read = {"path_id": result.get("path_id"), "kind": result.get("kind")}
        state.pending_read = {"path_id": result.get("path_id"), "kind": result.get("kind")}
        state.last_inline_source = _inline_source_from_read_result(result)
        return
    if tool_name == "skip_read":
        state.pending_read = None
        return
    if tool_name == "query_table":
        state.last_read = {"path_id": result.get("path_id"), "kind": result.get("kind")}
        state.last_inline_source = _inline_source_from_read_result(result)
        return
    if tool_name == "anchors":
        state.last_inline_source = {
            "tool": "anchors",
            "path": result.get("path"),
            "evidence_units": [
                (result.get("path"), "sentences", anchor.get("id"))
                for anchor in result.get("anchors", [])
                if anchor.get("id")
            ],
        }
        return
    state.pending_read = None
    state.last_read = None
    state.last_inline_source = None


def _inline_source_from_read_result(result: dict[str, Any]) -> dict[str, Any] | None:
    path_id = result.get("path_id")
    text = result.get("text") or ""
    if not isinstance(path_id, str) or not isinstance(text, str):
        return None
    kind = result.get("kind")
    if kind == "list":
        return {
            "tool": "read",
            "path_id": path_id,
            "evidence_units": [(path_id, "items", item_id) for item_id in _inline_ids(text, r"\[(I\d{3}(?:\.\d{3})*)\]")],
        }
    if kind in {"table", "table_query"}:
        return {
            "tool": "query_table" if kind == "table_query" else "read",
            "path_id": path_id,
            "evidence_units": [(path_id, "rows", row_id) for row_id in _inline_ids(text, r"\|\s*(R\d{3})\s*\|")],
        }
    return None


def _inline_ids(text: str, pattern: str) -> list[str]:
    return list(dict.fromkeys(re.findall(pattern, text)))


def _emit_event(state: Any, payload: dict[str, Any]) -> None:
    event = {"seq": state.next_seq, **payload}
    state.next_seq += 1
    state.events.append(event)


__all__ = [
    "build_tools",
    "_tree",
    "_read",
    "_bind_evidence",
    "_review_evidences",
    "_skip_read",
    "_write_field",
    "_submit_result",
]
