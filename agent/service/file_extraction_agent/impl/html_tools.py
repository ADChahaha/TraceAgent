"""Model-facing tools for virtual-tree file extraction."""

from __future__ import annotations

import json
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
    def tree(path_id: str = "", depth: int = 3) -> dict[str, Any]:
        """Expand the virtual semantic HTML file tree at a directory evidence link.

        Use this for directories: root, document directories, and section directories. Leave
        path_id empty for the root. Use evidence links such as evidence://0001 copied
        from tree output for document or section directories. Directory names
        are shown with a trailing slash in tree output. tree returns child directories and
        readable .md/.list/.table evidence links; it does not return file text. If you need
        content inside a directory, call tree on that directory first, then call read on one
        of the child .md/.list/.table evidence links.
        """

        return _tree(state, path_id, depth=depth)

    @tool
    def read(path_id: str) -> dict[str, Any]:
        """Read a file evidence link ending in .md, .list, or .table from tree output.

        Use evidence links such as evidence://0001.0001.0002 copied from tree output. Never
        call read on document or section directories. If tree shows a directory ending with
        /, call tree on that directory first, then read a child .md/.list/.table evidence
        link.
        Paragraph .md files return plain text without sentence ids. List and table reads
        return the whole object as Markdown with Ixxx item ids or Rxxx row ids.
        Each read call returns exactly one paragraph, list, or table block.
        read does not require an immediate add_candidate_evidence; continue browsing as needed.
        After seeing the result, narrate what this block is and what it contains —
        with actual values, not abstract layout descriptions.
        Leave adjacent reads silent until they form a meaningful chunk worth narrating.
        Use evidence links at appropriate granularity: section links for overviews,
        block links for specific tables/lists, inline selectors only for extracted values.
        Not every sentence needs a link. For consecutive blocks, use evidence://range/<start>/<end>.
        """

        return _read(state, path_id)

    @tool
    def add_candidate_evidence(
        field_id: str = "",
        path_id: str = "",
    ) -> dict[str, Any]:
        """Save one readable block as candidate evidence for a field.

        Use exactly one field_id and one path_id evidence link. One call saves
        one paragraph, list, or table block for one field. If the same block may help
        another field, or a field needs another block, call add_candidate_evidence again.
        This is broad note-taking, not the final evidence decision; possible relevance is enough.
        Candidate saves are normally silent — no assistant content needed unless the
        candidate changes the evidence picture in a way worth narrating.
        Do not pass sentence/item/row inline links; this tool records only block-level
        evidence links pointing to .md/.list/.table files.
        Call review_evidences later to expand into inline selectors.
        """

        return _add_candidate_evidence(state, field_id, path_id=path_id)

    @tool
    def review_evidences(field_id: str) -> dict[str, Any]:
        """Review one field's candidates and expose inline selectors for final evidence.

        Expands block candidates into inline evidence links:
        paragraphs → evidence://.../Sxxx, lists → evidence://.../Ixxx,
        tables → evidence://.../Rxxx. Also returns evidence_texts.
        Copy useful inline links from the result into write_field(final_evidence=...).
        Review is normally silent. Only narrate if evidence sufficiency changes in a
        way that matters — e.g. something is clearly missing or contradictory.
        When review shows enough evidence, call write_field next.
        """

        return _review_evidences(state, field_id)

    @tool
    def write_field(
        field_id: str,
        value: Any,
        final_evidence: list[str] | None = None,
        status: str = "resolved",
    ) -> dict[str, Any]:
        """Write or overwrite one schema field value with selected final evidence.

        Call after review_evidences for the same field.
        final_evidence must copy inline evidence:// links from review_evidences.evidence.
        If more candidates were added after review, review again before writing.
        Do not use block-level evidence links as final_evidence.
        Use status="resolved" for extracted values and status="missing" when the document
        does not support the field. Array fields must be written as a complete array.
        When narrating, state the extracted fact naturally with an evidence link —
        do not say 'field written as X' or 'filled X into Y'.
        """

        return _write_field(state, field_id, value, final_evidence=final_evidence, status=status)

    @tool
    def submit_result() -> dict[str, Any]:
        """Validate the current result buffer and submit the final extraction result.

        submit_result checks required fields, value types, enum variants, and evidence.
        Only null-typed fields or null enum variants may use final_evidence=[]. Resolved
        non-null values and non-null enum variants require non-empty final_evidence. If
        submit_result returns errors, fix the indicated fields and submit again.
        """

        return _submit_result(state)

    return [tree, read, add_candidate_evidence, review_evidences, write_field, submit_result]


EVIDENCE_LOCATOR_RE = re.compile(r"^evidence://(?P<path_id>\d{4}(?:\.\d{4})*)(?:/(?P<selector>[SIR]\d{3}(?:\.\d{3})*))?$")
PATH_ID_RE = re.compile(r"(?<![A-Za-z0-9_/:])(\d{4}(?:\.\d{4})*)(?![A-Za-z0-9_.])")
INLINE_SELECTOR_KEYS = {"S": "sentences", "I": "items", "R": "rows"}


def _tree(state: Any, path_id: str = "", *, depth: int = 3) -> dict[str, Any]:
    canonical_path_id = _tree_path_id_from_locator(path_id)
    return _run_tool(
        state,
        "tree",
        {"path_id": path_id, "depth": depth},
        lambda: _locator_error(path_id, canonical_path_id) or _tree_result(state, canonical_path_id, depth),
    )


def _read(
    state: Any,
    path_id: str,
) -> dict[str, Any]:
    canonical_path_id = _block_path_id_from_locator(path_id)
    return _run_tool(
        state,
        "read",
        {"path_id": path_id},
        lambda: _locator_error(path_id, canonical_path_id)
        or {"ok": True, **_expose_read_result(state.document.read_markdown(canonical_path_id))},
    )


def _anchors(state: Any, path: str) -> dict[str, Any]:
    try:
        ordering_error = validate_inline_request_after_read(state, path)
    except ValueError as exc:
        ordering_error = {"code": "INLINE_REQUIRES_READ", "message": str(exc)}
    if ordering_error:
        return _run_tool(
            state,
            "anchors",
            {"path": path},
            lambda: {"ok": False, "errors": [ordering_error]},
        )
    return _run_tool(
        state,
        "anchors",
        {"path": path},
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
) -> dict[str, Any]:
    return _run_tool(
        state,
        "query_table",
        {"path": path, "sql": sql, "offset": offset, "limit": limit},
        lambda: {"ok": True, **state.document.query_table(path, sql, offset=offset, limit=limit)},
    )


def _add_candidate_evidence(
    state: Any,
    field_id: str = "",
    *,
    path_id: str = "",
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        if not isinstance(field_id, str) or not field_id:
            errors.append({"field_id": field_id, "code": "BAD_CANDIDATE", "message": "field_id is required"})
        elif field_definition(state, field_id) is None:
            errors.append({"field_id": field_id, "code": "UNKNOWN_FIELD", "message": "unknown field_id"})

        canonical_path_id = _block_path_id_from_locator(path_id)
        if not isinstance(path_id, str) or not path_id.strip():
            errors.append({"field_id": field_id, "code": "CANDIDATE_PATH_REQUIRED", "message": "path_id is required"})
        elif canonical_path_id is None:
            errors.append(
                {
                    "field_id": field_id,
                    "path_id": path_id,
                    "code": "BAD_LOCATOR",
                    "message": "use a block evidence link like evidence://0001.0001.0001 copied from tree output",
                }
            )
        else:
            try:
                canonical_path_id = state.document.canonical_path_id(canonical_path_id)
                state.document.file_kind(canonical_path_id)
            except ValueError:
                errors.append(
                    {
                        "field_id": field_id,
                        "path_id": path_id,
                        "code": "UNREADABLE_CANDIDATE_PATH",
                        "message": "evidence link must point to a readable .md/.list/.table file",
                    }
                )
        if errors:
            return {"ok": False, "errors": errors}

        selector = {"path_id": canonical_path_id}
        existing = state.evidence_states.get(field_id, {})
        combined = list(existing.get("evidence") or [])
        if selector not in combined:
            combined.append(selector)
        state.evidence_states[field_id] = {
            "field_id": field_id,
            "evidence": combined,
        }
        state.review_states.pop(field_id, None)
        return {
            "ok": True,
            "field_id": field_id,
            "candidate_evidence": _block_links(combined),
        }

    result = _run_tool(
        state,
        "add_candidate_evidence",
        {"field_id": field_id, "path_id": path_id},
        execute,
    )
    if result.get("ok") is True:
        _emit_event(
            state,
            {
                "type": "candidate_evidence_added",
                "tool": "add_candidate_evidence",
                "field_id": result["field_id"],
                "candidate_evidence": result["candidate_evidence"],
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
) -> dict[str, Any]:
    action_text = _current_action_text(state)
    final_evidence = final_evidence or []

    def execute() -> dict[str, Any]:
        normalized_value = normalize_write_value(state, field_id, value)
        canonical_final_evidence, locator_errors = _canonicalize_final_evidence_links(final_evidence)
        errors = validate_field_write(state, field_id, normalized_value, status)
        errors.extend(locator_errors)
        errors.extend(validate_final_evidence_write(state, field_id, canonical_final_evidence, normalized_value, status))
        if errors:
            return {"ok": False, "errors": errors}
        evidence_texts = state.document.evidence_texts(canonical_final_evidence)
        field = {
            "field_id": field_id,
            "status": status,
            "value": normalized_value,
            "evidence": canonical_final_evidence,
            "evidence_texts": evidence_texts,
            "reason": action_text,
        }
        state.field_states[field_id] = field
        return {"ok": True, "field": _field_for_tool(field)}

    result = _run_tool(
        state,
        "write_field",
        {"field_id": field_id, "value": value, "final_evidence": final_evidence, "status": status},
        execute,
    )
    if result.get("ok") is True:
        _emit_event(
            state,
            {
                "type": "field_written",
                "tool": "write_field",
                "field": result["field"],
            },
        )
    return result


def _review_evidences(state: Any, field_id: str) -> dict[str, Any]:
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
        }
        return {
            "ok": True,
            "field_id": field_id,
            "field_description": getattr(field, "description", "") or "",
            "field": _field_for_tool(field_state) if field_state else None,
            "candidate_evidence": _block_links(candidate_evidence),
            "evidence": _inline_links(evidence),
            "evidence_texts": _evidence_texts_for_tool(evidence_texts),
            "guidance": (
                "This tool does not judge correctness. Copy only useful inline evidence links from "
                "review_evidences.evidence into write_field(final_evidence=...)."
            ),
        }

    return _run_tool(
        state,
        "review_evidences",
        {"field_id": field_id},
        execute,
    )


def _submit_result(state: Any) -> dict[str, Any]:
    result = _run_tool(
        state,
        "submit_result",
        {},
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
                "result": result["result"],
                "trace": trace,
            },
        )
    return result


def _tree_result(state: Any, path_id: str, depth: int) -> dict[str, Any]:
    canonical_path_id = state.document.path_id(path_id)
    return {
        "ok": True,
        "locator": _block_link(canonical_path_id),
        "depth": depth,
        "text": _link_tree_text(state.document.tree_text(canonical_path_id, depth=depth)),
    }


def model_tree_text(document: Any, path: str = "/", depth: int = 3) -> str:
    return _link_tree_text(document.tree_text(path, depth=depth))


def _locator_error(locator: Any, canonical_path_id: str | None) -> dict[str, Any] | None:
    if isinstance(locator, str) and canonical_path_id:
        return None
    return {
        "ok": False,
        "errors": [
            {
                "code": "BAD_LOCATOR",
                "message": "use an evidence link like evidence://0001 copied from tree output",
            }
        ],
    }


def _block_path_id_from_locator(locator: Any) -> str | None:
    parsed = _parse_evidence_locator(locator)
    if parsed is None:
        return None
    path_id, selector = parsed
    if selector is not None:
        return None
    return path_id


def _tree_path_id_from_locator(locator: Any) -> str | None:
    if locator in ("", None):
        return "0000"
    if isinstance(locator, str) and locator.strip() == "/":
        return "0000"
    return _block_path_id_from_locator(locator)


def _parse_evidence_locator(locator: Any) -> tuple[str, str | None] | None:
    if not isinstance(locator, str):
        return None
    match = EVIDENCE_LOCATOR_RE.fullmatch(locator.strip())
    if match is None:
        return None
    return match.group("path_id"), match.group("selector")


def _block_link(path_id: str) -> str:
    return f"evidence://{path_id}"


def _inline_link(path_id: str, selector: str) -> str:
    return f"{_block_link(path_id)}/{selector}"


def _block_links(evidence: list[dict[str, Any]] | None) -> list[str]:
    links: list[str] = []
    for selector in evidence or []:
        path_id = selector.get("path_id") if isinstance(selector, dict) else None
        if isinstance(path_id, str):
            links.append(_block_link(path_id))
    return links


def _inline_links(evidence: list[dict[str, Any]] | None) -> list[str]:
    links: list[str] = []
    for selector in evidence or []:
        if not isinstance(selector, dict):
            continue
        path_id = selector.get("path_id")
        if not isinstance(path_id, str):
            continue
        for key in ("sentences", "items", "rows"):
            values = selector.get(key)
            if isinstance(values, list):
                links.extend(_inline_link(path_id, str(value)) for value in values)
    return links


def _canonicalize_final_evidence_links(final_evidence: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if final_evidence in (None, []):
        return [], []
    if not isinstance(final_evidence, list):
        return [], [{"code": "BAD_FINAL_EVIDENCE", "message": "final_evidence must be a list of evidence:// inline links"}]
    grouped: dict[tuple[str, str], list[str]] = {}
    errors: list[dict[str, Any]] = []
    for index, locator in enumerate(final_evidence):
        parsed = _parse_evidence_locator(locator)
        if parsed is None:
            errors.append(
                {
                    "index": index,
                    "code": "BAD_FINAL_EVIDENCE_LOCATOR",
                    "message": "final_evidence entries must be inline evidence links like evidence://0001.0001.0001/S001",
                }
            )
            continue
        path_id, inline_id = parsed
        if inline_id is None:
            grouped.setdefault((path_id, ""), [])
            continue
        selector_key = INLINE_SELECTOR_KEYS.get(inline_id[0])
        if selector_key is None:
            errors.append(
                {
                    "index": index,
                    "code": "BAD_FINAL_EVIDENCE_LOCATOR",
                    "message": "inline evidence links must use Sxxx, Ixxx, or Rxxx selectors",
                }
            )
            continue
        grouped.setdefault((path_id, selector_key), [])
        if inline_id not in grouped[(path_id, selector_key)]:
            grouped[(path_id, selector_key)].append(inline_id)
    canonical = [
        {"path_id": path_id} if not key else {"path_id": path_id, key: values}
        for (path_id, key), values in grouped.items()
    ]
    return canonical, errors


def _expose_read_result(result: dict[str, Any]) -> dict[str, Any]:
    exposed: dict[str, Any] = {}
    for key, value in result.items():
        if key == "path_id" and isinstance(value, str):
            exposed["locator"] = _block_link(value)
        elif key == "returned_path_ids" and isinstance(value, list):
            exposed["returned_locators"] = [_block_link(item) if isinstance(item, str) else item for item in value]
        elif key == "blocks" and isinstance(value, list):
            exposed["blocks"] = [_expose_read_result(block) if isinstance(block, dict) else block for block in value]
        elif key == "text" and isinstance(value, str):
            exposed["text"] = _link_tree_text(value)
        else:
            exposed[key] = value
    return exposed


def _link_tree_text(text: str) -> str:
    linked_lines: list[str] = []
    for line in text.splitlines():
        linked = re.sub(
            r"^([│\s]*(?:[├└]── )?)(\d{4}(?:\.\d{4})*)\b",
            lambda match: f"{match.group(1)}{_block_link(match.group(2))}",
            line,
        )
        linked = re.sub(
            r"^path_id:\s*(\d{4}(?:\.\d{4})*)\s*$",
            lambda match: f"locator: {_block_link(match.group(1))}",
            linked,
        )
        linked = re.sub(
            r"^(## )(\d{4}(?:\.\d{4})*)(.*)$",
            lambda match: f"{match.group(1)}{_block_link(match.group(2))}{match.group(3)}",
            linked,
        )
        linked_lines.append(linked)
    return "\n".join(linked_lines)


def _evidence_texts_for_tool(evidence_texts: list[dict[str, str]]) -> list[dict[str, str]]:
    exposed = []
    for item in evidence_texts:
        path_id = item.get("path_id")
        selector = item.get("selector")
        locator = _inline_link(path_id, selector) if path_id and selector else ""
        exposed.append({"locator": locator, "selector": selector or "", "text": item.get("text", "")})
    return exposed


def _field_for_tool(field: dict[str, Any]) -> dict[str, Any]:
    return {
        **field,
        "evidence": _inline_links(field.get("evidence") or []),
        "evidence_texts": _evidence_texts_for_tool(field.get("evidence_texts") or []),
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


def normalize_write_value(state: Any, field_id: str, value: Any) -> Any:
    field = field_definition(state, field_id)
    if field is None or getattr(field, "type", "") != "enum" or not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return parsed


def validate_final_evidence_write(
    state: Any,
    field_id: str,
    final_evidence: list[dict[str, Any]],
    value: Any,
    status: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    field = field_definition(state, field_id)
    if field is None:
        return errors
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
    if review_state is None:
        if final_units:
            return [
                {
                    "field_id": field_id,
                    "code": "UNREVIEWED_FINAL_EVIDENCE",
                    "message": "final_evidence must be selected from review_evidences.evidence for this field",
                }
            ]
        return [
            {
                "field_id": field_id,
                "code": "REVIEW_REQUIRED",
                "message": "write_field requires a prior review_evidences snapshot for this field",
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
                "code": "CANDIDATE_REQUIRES_INLINE",
                "message": "add_candidate_evidence must immediately follow anchors, read, or query_table that exposed the referenced inline ids",
            }
        ]
    if not evidence_units.issubset(inline_units):
        return [
            {
                "code": "CANDIDATE_REQUIRES_INLINE",
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
    trace = {
        "events": list(state.events),
        "actions": list(state.actions),
        "document_tree": state.document.outline_tree(),
        "source_selectors": state.document.source_selectors(),
    }
    return {"ok": True, "result": result, "trace": trace}


def field_definition(state: Any, field_id: str) -> Any:
    for field in state.task_spec.fields:
        if field.name == field_id:
            return field
    return None


def _field_with_evidence_texts(state: Any, field_state: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        **field_state,
        "field_name": field_state.get("field_id"),
    }
    normalized.pop("field_id", None)
    if "evidence_texts" in normalized:
        return normalized
    return {
        **normalized,
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
    execute,
    *,
    emit_result_completed: bool = True,
) -> dict[str, Any]:
    _emit_event(
        state,
        {
            "type": "tool_started",
            "tool": tool_name,
            "args": args,
        },
    )
    ordering_error = validate_tool_order(state, tool_name)
    if ordering_error:
        result = {"ok": False, "errors": [ordering_error]}
        _record_action(state, tool_name, args, result)
        _emit_event(
            state,
            {
                "type": "tool_failed",
                "tool": tool_name,
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
    _record_action(state, tool_name, args, event_result)
    _update_tool_cursor(state, tool_name, event_result)
    _emit_event(
        state,
        {
            "type": event_type,
            "tool": tool_name,
            "args": args,
            "result": event_result,
        },
    )
    return result


def validate_tool_order(state: Any, tool_name: str) -> dict[str, Any] | None:
    return None


def _record_action(state: Any, tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    state.actions.append(
        {
            "tool_name": tool_name,
            "args": args,
            "result": result,
        }
    )


def _current_action_text(state: Any) -> str:
    content = getattr(state, "current_model_content", "")
    return content if isinstance(content, str) else ""


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
    if tool_name == "add_candidate_evidence":
        return
    if tool_name == "read":
        state.last_read = {"path_id": _result_path_id(result), "kind": result.get("kind")}
        state.pending_read = None
        state.last_inline_source = _inline_source_from_read_result(result)
        return
    if tool_name == "query_table":
        state.last_read = {"path_id": _result_path_id(result), "kind": result.get("kind")}
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


def _inline_source_from_read_result(result: dict[str, Any]) -> dict[str, Any] | None:
    path_id = _result_path_id(result)
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


def _result_path_id(result: dict[str, Any]) -> str | None:
    path_id = result.get("path_id")
    if isinstance(path_id, str):
        return path_id
    locator_path_id = _block_path_id_from_locator(result.get("locator"))
    return locator_path_id


def _inline_ids(text: str, pattern: str) -> list[str]:
    return list(dict.fromkeys(re.findall(pattern, text)))


def _emit_event(state: Any, payload: dict[str, Any]) -> None:
    event = {"seq": state.next_seq, **payload}
    state.next_seq += 1
    state.events.append(event)


__all__ = [
    "build_tools",
    "model_tree_text",
    "_tree",
    "_read",
    "_add_candidate_evidence",
    "_review_evidences",
    "_write_field",
    "_submit_result",
]
