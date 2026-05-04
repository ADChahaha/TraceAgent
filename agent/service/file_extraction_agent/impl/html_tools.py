"""Resolution tools for HTML extraction.

The public functions exposed to the model are created by ``build_tools``. Each
wrapper hides ``GraphState`` from the model while binding the current run state
through a closure. Internal implementation functions keep ``state`` explicit so
they remain straightforward to unit test.
"""

from __future__ import annotations

import re
import sqlite3
from html import escape
from typing import Any

LARGE_TABLE_SELECT_STAR_ROW_LIMIT = 30
LARGE_TABLE_SELECT_STAR_CELL_LIMIT = 300
MAX_LARGE_TABLE_SELECT_STAR_LIMIT = 50

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover - import fallback for early tests
    def tool(function=None, *args: Any, **kwargs: Any):  # type: ignore[no-redef]
        if function is None:
            return lambda wrapped: wrapped
        return function


def build_tools(state: Any) -> list[Any]:
    """Build model-facing resolution tools bound to the current graph state."""

    @tool
    def update_plan(plan_index: int, status: str, reason: str) -> dict[str, Any]:
        """
        Mark one broad-plan step as in progress or completed.

        Use this to keep the replay plan synchronized with your actual work.
        Call ``update_plan(plan_index, "in_progress", reason)`` before starting
        a broad-plan step, and call ``update_plan(plan_index, "completed",
        reason)`` immediately after the step has produced its field value,
        evidence, or routing decision. ``plan_index`` is 1-based and refers to
        the numbered Broad plan shown in the prompt. Plan steps must advance
        sequentially: only the earliest unfinished step may become
        ``in_progress``, and a step must be ``in_progress`` before it can be
        marked ``completed``.

        Args:
            plan_index: 1-based index of the Broad plan item.
            status: ``in_progress`` or ``completed``.
            reason: Short explanation of why this plan step now has that
                status.

        Returns:
            The stored plan status, or validation errors.
        """

        return _update_plan(state, plan_index, status, reason=reason)

    @tool
    def read_element(element_id: str, reason: str) -> dict[str, Any]:
        """
        Read one HTML element by its existing id.

        Use this after the built-in document outline shows a candidate element
        id and you need the element's detailed content. If the current field
        depends on several adjacent elements from the same section, call
        read_section on the parent heading with a larger depth instead of
        repeatedly calling read_element.

        Args:
            element_id: Existing HTML element id, for example ``dp-p-3`` or
                ``dp-table-1``.
            reason: Why this element is needed for the current field. Mention
                the current field name and what evidence you expect here.

        Returns:
            HTML-like element content and evidence ids. Table rows are not
            returned; use ``table_extraction`` for row data.
        """

        return _read_element(state, element_id, reason=reason)

    @tool
    def read_section(section_id: str, reason: str, depth: int = 1) -> dict[str, Any]:
        """
        Read a heading section by id, optionally including nested subsections.

        Use this when the document outline points to a section heading and you
        need the content under that heading. This is better than repeatedly
        calling read_element on the heading id. Prefer increasing depth over
        many read_element calls from the same section: use depth=1 for one
        narrow subsection, depth=2 for several adjacent child subsections, and
        depth=3 only for a complete major chapter.

        Args:
            section_id: Existing heading id, for example ``dp-h2-56``.
            reason: Why this section is needed for the current field. Mention
                the current field name and what evidence you expect here.
            depth: Number of nested heading levels to include. ``1`` reads the
                section content and direct child subsection headings/content;
                larger values include deeper subsections. Use ``depth=1`` for
                one narrow subsection, ``depth=2`` when the current field needs
                several adjacent child subsections, and ``depth=3`` only when
                the current field needs a complete major chapter. Prefer
                increasing depth over many read_element calls from the same
                section.

        Returns:
            HTML-like section map and evidence ids. Large lists are summarized
            as list references with a few item previews. Table rows are not
            returned; use ``table_extraction`` for row data.
        """

        return _read_section(state, section_id, depth, reason=reason)

    @tool
    def table_extraction(table_id: str, sql: str, reason: str) -> dict[str, Any]:
        """
        Query one HTML table using a SQL SELECT statement.

        Use this only after ``read_element(table_id)`` has shown the table
        columns. The SQL must be a single SELECT statement over table name
        ``data``. ``SELECT *`` is allowed for small tables. For large tables,
        prefer explicit columns and WHERE filters. If the table is messy and
        you truly need all columns, page through it with ``LIMIT 50`` or less.

        Examples:
        - Small table: ``SELECT * FROM data`` is acceptable.
        - Large table with clear columns: use
          ``SELECT "寝室名称", "类别" FROM data WHERE "类别" = '文明寝室'``.
        - Large messy table where WHERE is not reliable: use
          ``SELECT * FROM data LIMIT 50 OFFSET 0``, then continue with
          ``OFFSET 50`` if needed.
        - Never use unbounded ``SELECT *`` on a large table.

        Args:
            table_id: Existing HTML table id, for example ``dp-table-1``.
            sql: A single SELECT statement over table name ``data``, for
                example ``SELECT "姓名", "学号" FROM data WHERE "学院" = '计算机学院'``.
                Always wrap every column name in double quotes, especially
                Chinese names, names containing spaces, and names containing
                punctuation.
            reason: Why this SQL query is needed for the current field. Mention
                the current field name and what rows/columns you expect.

        Returns:
            On success, matching rows with values, row ids, and evidence ids.
            Evidence ids include the table id and matching row id. On SQL
            errors, returns ``{"ok": false, "error": "...", "columns": [...]}``;
            inspect the error and retry with corrected SQL.
        """

        return _table_extraction(state, table_id, sql, reason=reason)

    @tool
    def paragraph_extraction(element_id: str, pattern: str, reason: str) -> dict[str, Any]:
        """
        Search one text-like HTML element using a regex pattern.

        Use this for extracting values from TITLE, SECTION_HEADER, TEXT,
        LIST_ITEM, or CAPTION elements.

        Args:
            element_id: Existing HTML element id, for example ``dp-p-4``.
            pattern: Python regular expression pattern.
            reason: Why this regex search is needed for the current field.
                Mention the current field name and expected value.

        Returns:
            All regex matches with matched text, spans, and evidence ids.
        """

        return _paragraph_extraction(state, element_id, pattern, reason=reason)

    @tool
    def set_field(
        name: str,
        value: Any,
        evidence_ids: list[str],
        reason: str,
        status: str = "resolved",
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Set one output field with value and evidence ids.

        You must call this for each task field exactly once, either with
        ``status="resolved"`` when the value is supported, or with
        ``status="failed"`` when the field cannot be extracted. Call set_field
        as soon as enough evidence for the current field has been observed; do
        not keep reading unrelated elements first.

        Use this only after this same run has observed the supporting evidence
        through ``read_element``, ``table_extraction``, or
        ``paragraph_extraction``. Do not call this from document overview alone.

        Args:
            name: Field name declared in task_spec.
            value: Extracted field value. Use null when status is ``failed``.
            evidence_ids: Existing HTML ids supporting the value, such as
                ``["dp-p-4"]`` or ``["dp-table-1", "dp-tr-2"]``.
            status: ``resolved`` when a value is found, or ``failed`` when the
                field cannot be extracted.
            reason: Why this value is now sufficiently supported. Mention the
                evidence ids and the current field.
            failure_reason: Required when status is ``failed``.

        Returns:
            The stored field state or validation errors.
        """

        return _set_field(state, name, value, evidence_ids, status, failure_reason, reason=reason)

    @tool
    def finish() -> dict[str, Any]:
        """
        Finish the extraction run.

        Use this only after all task fields have been set either as ``resolved``
        or ``failed``. If this returns errors, fix the listed fields with
        set_field and call finish again.

        Returns:
            ``{"ok": true, "errors": []}`` when validation passes. If
            validation fails, returns ``{"ok": false, "errors": [...]}``.
        """

        return _finish(state)

    return [
        update_plan,
        read_element,
        read_section,
        table_extraction,
        paragraph_extraction,
        set_field,
        finish,
    ]


def _overview(state: Any) -> dict[str, Any]:
    result = {"tree": _read(state, "document").tree}
    _record_action(state, "overview", {}, _summarize_tool_result(result))
    return result


def _update_plan(state: Any, plan_index: int, status: str, *, reason: str | None = None) -> dict[str, Any]:
    try:
        index = int(plan_index)
    except (TypeError, ValueError):
        result = {"ok": False, "errors": [{"message": "plan_index must be an integer"}]}
        _record_action(state, "update_plan", _args_with_reason({"plan_index": plan_index, "status": status}, reason), result)
        return result

    plan_items = _read(_read(state, "broad_plan"), "plan", []) or []
    if index < 1 or index > len(plan_items):
        result = {
            "ok": False,
            "errors": [
                {
                    "message": "plan_index is outside the broad plan",
                    "plan_index": index,
                    "plan_count": len(plan_items),
                }
            ],
        }
        _record_action(state, "update_plan", _args_with_reason({"plan_index": index, "status": status}, reason), result)
        return result
    if status not in {"in_progress", "completed"}:
        result = {"ok": False, "errors": [{"message": "status must be in_progress or completed"}]}
        _record_action(state, "update_plan", _args_with_reason({"plan_index": index, "status": status}, reason), result)
        return result

    statuses = _read(state, "plan_statuses", None)
    if not isinstance(statuses, dict):
        statuses = {}
    sequence_error = _validate_plan_sequence(statuses, index, status, len(plan_items))
    if sequence_error is not None:
        result = {"ok": False, "errors": [sequence_error]}
        _record_action(state, "update_plan", _args_with_reason({"plan_index": index, "status": status}, reason), result)
        return result

    plan_state = {
        "plan_index": index,
        "status": status,
        "step": str(plan_items[index - 1]),
        "reason": reason,
    }
    if isinstance(statuses, dict):
        statuses[index] = plan_state
    _record_action(
        state,
        "update_plan",
        _args_with_reason({"plan_index": index, "status": status}, reason),
        {"ok": True, "plan": plan_state},
    )
    return {"ok": True, "plan": plan_state}


def _validate_plan_sequence(
    statuses: dict[Any, Any],
    index: int,
    status: str,
    plan_count: int,
) -> dict[str, Any] | None:
    current_status = _plan_status_at(statuses, index)
    next_index = _next_unfinished_plan_index(statuses, plan_count)
    if status == "in_progress":
        if current_status == "completed":
            return {
                "message": "plan is already completed",
                "plan_index": index,
            }
        if index != next_index:
            return {
                "message": "plan_index must advance sequentially",
                "requested_plan_index": index,
                "next_plan_index": next_index,
            }
        return None

    if current_status != "in_progress":
        return {
            "message": "plan must be in_progress before completed",
            "plan_index": index,
            "current_status": current_status,
        }
    return None


def _next_unfinished_plan_index(statuses: dict[Any, Any], plan_count: int) -> int:
    for index in range(1, plan_count + 1):
        if _plan_status_at(statuses, index) != "completed":
            return index
    return plan_count


def _plan_status_at(statuses: dict[Any, Any], index: int) -> str | None:
    raw = statuses.get(index, statuses.get(str(index)))
    if isinstance(raw, dict):
        value = raw.get("status")
    else:
        value = getattr(raw, "status", None)
    return value if value in {"in_progress", "completed"} else None


def _read_element(state: Any, element_id: str, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    element = document.elements_by_id.get(element_id)
    if element is None:
        result = {"ok": False, "error": f"unknown element id: {element_id}"}
        _record_action(state, "read_element", _args_with_reason({"element_id": element_id}, reason), result)
        return result

    if element.type == "TABLE":
        table = document.tables_by_id.get(element_id)
        if table is None:
            result = {"ok": False, "error": f"unknown table id: {element_id}"}
            _record_action(state, "read_element", _args_with_reason({"element_id": element_id}, reason), result)
            return result
        _mark_observed(state, [table.table_id])
        result = {
            "id": table.table_id,
            "type": "TABLE",
            "html": _element_html(document, element),
            "evidence_ids": [table.table_id],
            "sql_hint": (
                'Use table name data and wrap every column name in double quotes, '
                'for example SELECT "论文题目" FROM data WHERE "作品类型" = '
                "'学术论文'."
            ),
        }
        _record_action(state, "read_element", _args_with_reason({"element_id": element_id}, reason), result)
        return result

    _mark_observed(state, [element.id])
    result = {
        "id": element.id,
        "type": element.type,
        "html": _element_html(document, element),
        "evidence_ids": [element.id],
    }
    _record_action(state, "read_element", _args_with_reason({"element_id": element_id}, reason), result)
    return result


def _read_section(state: Any, section_id: str, depth: int = 1, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    section = document.elements_by_id.get(section_id)
    if section is None:
        result = {"ok": False, "error": f"unknown section id: {section_id}"}
        _record_action(state, "read_section", _args_with_reason({"section_id": section_id, "depth": depth}, reason), result)
        return result
    if section.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        result = {"ok": False, "error": f"element is not a section heading: {section_id}"}
        _record_action(state, "read_section", _args_with_reason({"section_id": section_id, "depth": depth}, reason), result)
        return result

    depth = max(0, int(depth))
    ordered = list(document.elements_by_id.values())
    start_index = next(
        (index for index, element in enumerate(ordered) if element.id == section_id),
        None,
    )
    if start_index is None:
        result = {"ok": False, "error": f"section id not found in document order: {section_id}"}
        _record_action(state, "read_section", _args_with_reason({"section_id": section_id, "depth": depth}, reason), result)
        return result

    start_level = _heading_level(section.tag)
    max_level = start_level + depth
    current_level = start_level
    items: list[dict[str, Any]] = []
    evidence_ids = [section_id]

    for element in ordered[start_index + 1 :]:
        element_level = _heading_level(element.tag)
        if element_level is not None:
            if element_level <= start_level:
                break
            current_level = element_level
            if element_level <= max_level:
                items.append(_section_item(document, element))
                evidence_ids.append(element.id)
            continue

        if (
            current_level <= max_level
            and element.tag not in {"tr", "caption"}
            and not _is_list_child(document, element)
        ):
            items.append(_section_item(document, element))
            evidence_ids.append(element.id)

    _mark_observed(state, evidence_ids)
    result = {
        "section_id": section_id,
        "depth": depth,
        "html": _section_html(document, section, items, depth),
        "evidence_ids": evidence_ids,
    }
    _record_action(state, "read_section", _args_with_reason({"section_id": section_id, "depth": depth}, reason), _summarize_tool_result(result))
    return result


def _table_extraction(state: Any, table_id: str, sql: str, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    table = document.tables_by_id.get(table_id)
    if table is None:
        result = {"ok": False, "error": f"unknown table id: {table_id}"}
        _record_action(state, "table_extraction", _args_with_reason({"table_id": table_id, "sql": sql}, reason), result)
        return result
    if not _is_safe_select(sql):
        result = {"ok": False, "error": "sql must be a single SELECT statement"}
        _record_action(state, "table_extraction", _args_with_reason({"table_id": table_id, "sql": sql}, reason), result)
        return result
    if _is_large_table_select_star(table, sql):
        result = {
            "ok": False,
            "error": "table is too large for unbounded SELECT *",
            "table_id": table_id,
            "row_count": len(table.rows),
            "column_count": len(table.columns),
            "cell_count": len(table.rows) * len(table.columns),
            "max_select_star_limit": MAX_LARGE_TABLE_SELECT_STAR_LIMIT,
            "columns": table.columns,
            "sql_hint": (
                "Select only the needed columns instead of SELECT *. "
                "Add a WHERE clause when possible. If the table is messy and "
                "you need all columns, use SELECT * FROM data LIMIT 50 OFFSET 0 "
                "and continue with OFFSET 50 if needed."
            ),
        }
        _record_action(state, "table_extraction", _args_with_reason({"table_id": table_id, "sql": sql}, reason), result)
        return result

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    quoted_columns = [_quote_identifier(column) for column in table.columns]
    connection.execute(
        f"CREATE TABLE data (__row_id TEXT, {', '.join(column + ' TEXT' for column in quoted_columns)})"
    )
    placeholders = ", ".join(["?"] * (len(table.columns) + 1))
    for row_id, row in zip(table.row_ids, table.rows, strict=False):
        values = [row_id] + [row.get(column, "") for column in table.columns]
        connection.execute(f"INSERT INTO data VALUES ({placeholders})", values)
    try:
        cursor = connection.execute(sql)
    except sqlite3.Error as exc:
        connection.close()
        result = {
            "ok": False,
            "error": str(exc),
            "table_id": table_id,
            "columns": table.columns,
            "sql_hint": (
                'Wrap every column name in double quotes. Example: '
                'SELECT "论文题目" FROM data WHERE "作品类型" = \'学术论文\'.'
            ),
        }
        _record_action(
            state,
            "table_extraction",
            _args_with_reason({"table_id": table_id, "sql": sql}, reason),
            result,
        )
        return result
    selected_columns = [description[0] for description in cursor.description or []]
    rows = []
    for sqlite_row in cursor.fetchall():
        row_id = sqlite_row["__row_id"] if "__row_id" in sqlite_row.keys() else None
        values = {
            column: sqlite_row[column]
            for column in selected_columns
            if column != "__row_id"
        }
        if row_id is None:
            row_id = _match_row_id(table, values)
        evidence_ids = [table_id, row_id] if row_id else [table_id]
        _mark_observed(state, evidence_ids)
        rows.append(
            {
                "row_id": row_id,
                "values": values,
                "evidence_ids": evidence_ids,
            }
        )
    connection.close()
    result = {
        "table_id": table_id,
        "columns": [column for column in selected_columns if column != "__row_id"],
        "rows": rows,
    }
    _record_action(state, "table_extraction", _args_with_reason({"table_id": table_id, "sql": sql}, reason), _summarize_tool_result(result))
    return result


def _paragraph_extraction(state: Any, element_id: str, pattern: str, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    element = document.elements_by_id.get(element_id)
    if element is None:
        result = {"ok": False, "error": f"unknown element id: {element_id}"}
        _record_action(state, "paragraph_extraction", _args_with_reason({"element_id": element_id, "pattern": pattern}, reason), result)
        return result
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        result = {"ok": False, "error": f"invalid regex: {exc}"}
        _record_action(state, "paragraph_extraction", _args_with_reason({"element_id": element_id, "pattern": pattern}, reason), result)
        return result

    matches = [
        {
            "text": match.group(0),
            "span": [match.start(), match.end()],
            "evidence_ids": [element_id],
        }
        for match in regex.finditer(element.text)
    ]
    if matches:
        _mark_observed(state, [element_id])
    result = {
        "element_id": element_id,
        "matches": matches,
    }
    _record_action(state, "paragraph_extraction", _args_with_reason({"element_id": element_id, "pattern": pattern}, reason), _summarize_tool_result(result))
    return result


def _set_field(
    state: Any,
    name: str,
    value: Any,
    evidence_ids: list[str],
    status: str,
    failure_reason: str | None,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    if status not in {"resolved", "failed"}:
        return {"ok": False, "errors": [{"field": name, "message": "invalid status"}]}
    if status == "failed" and not failure_reason:
        return {"ok": False, "errors": [{"field": name, "message": "failure_reason is required"}]}
    if name not in _field_defs_by_name(state):
        return {"ok": False, "errors": [{"field": name, "message": "unknown field"}]}

    invalid_ids = [evidence_id for evidence_id in evidence_ids if not _evidence_exists(state, evidence_id)]
    if invalid_ids:
        return {
            "ok": False,
            "errors": [{"field": name, "message": "unknown evidence ids", "ids": invalid_ids}],
        }
    unobserved_ids = [
        evidence_id
        for evidence_id in evidence_ids
        if evidence_id not in _read(state, "observed_evidence_ids", set())
    ]
    if status == "resolved" and unobserved_ids:
        return {
            "ok": False,
            "errors": [
                {
                    "field": name,
                    "message": "evidence ids must be observed by read/extraction tools before set_field",
                    "ids": unobserved_ids,
                }
            ],
        }

    field_state = {
        "name": name,
        "status": status,
        "value": value,
        "evidence_ids": list(evidence_ids),
            "failure_reason": failure_reason,
            "reason": reason,
        }
    _read(state, "field_states")[name] = field_state
    _record_action(
        state,
        "set_field",
        _args_with_reason({"name": name, "value": value, "evidence_ids": evidence_ids, "status": status}, reason),
        {"ok": True, "field": field_state},
    )
    return {"ok": True, "field": field_state}


def _finish(state: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    field_states = _read(state, "field_states")
    for name, field_def in _field_defs_by_name(state).items():
        field_state = field_states.get(name)
        if _read(field_def, "required", False) and field_state is None:
            errors.append({"field": name, "message": "required field is missing"})
            continue
        if field_state is None:
            continue
        if field_state.get("status") == "resolved":
            if not field_state.get("evidence_ids"):
                errors.append({"field": name, "message": "resolved field requires evidence"})
            if not _value_matches_type(field_state.get("value"), _read(field_def, "type", "string")):
                errors.append({"field": name, "message": "field value does not match type"})
    result = {"ok": not errors, "errors": errors}
    _record_action(state, "finish", {}, result)
    return result


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _field_defs_by_name(state: Any) -> dict[str, Any]:
    task_spec = _read(state, "task_spec")
    fields = _read(task_spec, "fields", []) or []
    return {str(_read(field, "name")): field for field in fields if _read(field, "name")}


def _evidence_exists(state: Any, evidence_id: str) -> bool:
    document = _read(state, "document")
    return evidence_id in document.elements_by_id or evidence_id in document.row_index


def _record_action(state: Any, tool_name: str, args: dict[str, Any], result: Any) -> None:
    actions = _read(state, "actions", None)
    if isinstance(actions, list):
        actions.append({"tool_name": tool_name, "args": args, "result": result})


def _summarize_tool_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    summary = dict(result)
    if "tree" in summary and isinstance(summary["tree"], list):
        summary["tree_node_count"] = _count_tree_nodes(summary["tree"])
        summary.pop("tree", None)
    if "rows" in summary and isinstance(summary["rows"], list):
        summary["row_count"] = len(summary["rows"])
    if "matches" in summary and isinstance(summary["matches"], list):
        summary["match_count"] = len(summary["matches"])
    if "html" in summary and isinstance(summary["html"], str):
        summary["html_chars"] = len(summary["html"])
    return summary


def _count_tree_nodes(nodes: list[Any]) -> int:
    total = 0
    for node in nodes:
        total += 1
        if isinstance(node, dict):
            total += _count_tree_nodes(node.get("children", []) or [])
    return total


def _mark_observed(state: Any, evidence_ids: list[str]) -> None:
    observed = _read(state, "observed_evidence_ids", None)
    if observed is None:
        try:
            observed = set()
            setattr(state, "observed_evidence_ids", observed)
        except Exception:
            return
    observed.update(evidence_id for evidence_id in evidence_ids if evidence_id)


def _is_safe_select(sql: str) -> bool:
    normalized = sql.strip().rstrip(";").strip()
    if ";" in normalized:
        return False
    if not normalized.lower().startswith("select "):
        return False
    forbidden = {"insert", "update", "delete", "drop", "attach", "pragma", "create", "alter"}
    return not any(re.search(rf"\b{word}\b", normalized, flags=re.IGNORECASE) for word in forbidden)


def _is_large_table_select_star(table: Any, sql: str) -> bool:
    if not _selects_all_columns(sql):
        return False
    row_count = len(_read(table, "rows", []) or [])
    column_count = len(_read(table, "columns", []) or [])
    is_large = (
        row_count > LARGE_TABLE_SELECT_STAR_ROW_LIMIT
        or row_count * column_count > LARGE_TABLE_SELECT_STAR_CELL_LIMIT
    )
    if not is_large:
        return False
    limit = _select_limit(sql)
    return limit is None or limit > MAX_LARGE_TABLE_SELECT_STAR_LIMIT


def _selects_all_columns(sql: str) -> bool:
    normalized = sql.strip().rstrip(";").strip()
    match = re.match(r"(?is)^select\s+(.*?)\s+from\s+data\b", normalized)
    if not match:
        return False
    selected = match.group(1).strip()
    return selected == "*" or re.fullmatch(r"(?:data|\"data\")\s*\.\s*\*", selected, flags=re.IGNORECASE) is not None


def _select_limit(sql: str) -> int | None:
    normalized = sql.strip().rstrip(";").strip()
    match = re.search(r"(?is)\blimit\s+(\d+)\b", normalized)
    if not match:
        return None
    return int(match.group(1))


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _match_row_id(table: Any, values: dict[str, Any]) -> str | None:
    for row_id, row in zip(table.row_ids, table.rows, strict=False):
        if all(str(row.get(column, "")) == str(value) for column, value in values.items()):
            return row_id
    return None


def _heading_level(tag: str) -> int | None:
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return int(tag[1])
    return None


def _section_item(document: Any, element: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": element.id,
        "type": element.type,
    }
    if element.type == "TABLE":
        table = document.tables_by_id.get(element.id)
        item["columns"] = table.columns if table else []
        item["header_row_id"] = table.header_row_id if table else None
        item["row_count"] = len(table.rows) if table else 0
    else:
        item["text"] = element.text
    return item


def _element_html(document: Any, element: Any) -> str:
    if element.type == "TABLE":
        table = document.tables_by_id.get(element.id)
        columns = " | ".join(table.columns if table else [])
        row_count = len(table.rows) if table else 0
        header_row_id = table.header_row_id if table else ""
        label = table.label if table else ""
        label_attr = f' label="{_attr(label)}"' if label else ""
        return (
            f'<table-ref id="{_attr(element.id)}"{label_attr} rows="{_attr(row_count)}" '
            f'header-row-id="{_attr(header_row_id)}" columns="{_attr(columns)}" />'
        )
    tag = _html_like_tag(element)
    return f'<{tag} id="{_attr(element.id)}">{_text(element.text)}</{tag}>'


def _section_html(document: Any, section: Any, items: list[dict[str, Any]], depth: int) -> str:
    lines = [
        f'<section id="{_attr(section.id)}" title="{_attr(section.text)}" depth="{_attr(depth)}">'
    ]
    for item in items:
        lines.extend(_section_item_html_lines(document, item, indent="  "))
    lines.append("</section>")
    return "\n".join(lines)


def _section_item_html_lines(document: Any, item: dict[str, Any], indent: str) -> list[str]:
    item_id = item["id"]
    item_type = item["type"]
    if item_type == "TABLE":
        columns = " | ".join(str(column) for column in item.get("columns", []) or [])
        table = document.tables_by_id.get(item_id)
        label = table.label if table else ""
        label_attr = f' label="{_attr(label)}"' if label else ""
        return [
            f'{indent}<table-ref id="{_attr(item_id)}"{label_attr} rows="{_attr(item.get("row_count", 0))}" '
            f'header-row-id="{_attr(item.get("header_row_id", ""))}" columns="{_attr(columns)}" />'
        ]
    if item_type == "TEXT" and _element_tag(document, item_id) in {"ul", "ol"}:
        return _list_ref_html_lines(document, item_id, indent)
    tag = _html_like_tag(item)
    text = _preview(str(item.get("text", "")))
    return [f'{indent}<{tag} id="{_attr(item_id)}">{_text(text)}</{tag}>']


def _list_ref_html_lines(document: Any, list_id: str, indent: str) -> list[str]:
    item_ids = [
        element.id
        for element in document.elements_by_id.values()
        if element.parent_id == list_id and element.tag == "li"
    ]
    lines = [f'{indent}<list-ref id="{_attr(list_id)}" items="{_attr(len(item_ids))}">']
    for item_id in item_ids[:3]:
        element = document.elements_by_id[item_id]
        lines.append(
            f'{indent}  <item-ref id="{_attr(item_id)}">{_text(_preview(element.text))}</item-ref>'
        )
    remaining = len(item_ids) - 3
    if remaining > 0:
        lines.append(f'{indent}  <truncated remaining="{_attr(remaining)}" />')
    lines.append(f"{indent}</list-ref>")
    return lines


def _element_tag(document: Any, element_id: str) -> str:
    element = document.elements_by_id.get(element_id)
    return element.tag if element else ""


def _is_list_child(document: Any, element: Any) -> bool:
    if element.tag != "li" or not element.parent_id:
        return False
    return _element_tag(document, element.parent_id) in {"ul", "ol"}


def _html_like_tag(element: Any) -> str:
    element_type = element["type"] if isinstance(element, dict) else element.type
    if element_type == "TITLE":
        return "title"
    if element_type == "SECTION_HEADER":
        return "heading"
    if element_type == "LIST_ITEM":
        return "item"
    if element_type == "CAPTION":
        return "caption"
    return "text"


def _preview(text: str, limit: int = 160) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _attr(value: Any) -> str:
    return escape(str(value), quote=True)


def _text(value: Any) -> str:
    return escape(str(value), quote=False)


def _value_matches_type(value: Any, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "list[string]":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if field_type == "list[number]":
        return isinstance(value, list) and all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)
    return True


def _args_with_reason(args: dict[str, Any], reason: str | None) -> dict[str, Any]:
    if reason is None:
        return args
    return {**args, "reason": reason}


__all__ = [
    "build_tools",
    "_overview",
    "_update_plan",
    "_read_element",
    "_table_extraction",
    "_paragraph_extraction",
    "_set_field",
    "_finish",
]
