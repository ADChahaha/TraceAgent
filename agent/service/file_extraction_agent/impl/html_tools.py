"""Resolution tools for HTML extraction.

The public functions exposed to the model are created by ``build_tools``. Each
wrapper hides ``GraphState`` from the model while binding the current run state
through a closure. Internal implementation functions keep ``state`` explicit so
they remain straightforward to unit test.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

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
    def overview() -> dict[str, Any]:
        """
        Return the document tree built from the input HTML.

        Use this first to understand the document structure and locate candidate
        element ids for headings, text, list items, captions, and tables.

        Returns:
            A JSON object with key ``tree``. The tree contains existing HTML ids,
            semantic node types, short text, and children. Table nodes include
            columns and row counts, not full table rows.
        """

        return _overview(state)

    @tool
    def read_element(element_id: str) -> dict[str, Any]:
        """
        Read one HTML element by its existing id.

        Use this after ``overview`` returns a candidate element id and you need
        the element's detailed content.

        Args:
            element_id: Existing HTML element id, for example ``dp-p-3`` or
                ``dp-table-1``.

        Returns:
            For text-like elements, returns id, type, and full text. For table
            elements, returns id, type, columns, header row id, and row count.
            Table rows are not returned; use ``table_extraction`` for row data.
        """

        return _read_element(state, element_id)

    @tool
    def table_extraction(table_id: str, sql: str) -> dict[str, Any]:
        """
        Query one HTML table using a SQL SELECT statement.

        Use this only after ``read_element(table_id)`` has shown the table
        columns. The SQL must be a single SELECT statement over table name
        ``data``.

        Args:
            table_id: Existing HTML table id, for example ``dp-table-1``.
            sql: A single SELECT statement over table name ``data``, for
                example ``SELECT "姓名", "学号" FROM data WHERE "学院" = '计算机学院'``.
                Always wrap every column name in double quotes, especially
                Chinese names, names containing spaces, and names containing
                punctuation.

        Returns:
            On success, matching rows with values, row ids, and evidence ids.
            Evidence ids include the table id and matching row id. On SQL
            errors, returns ``{"ok": false, "error": "...", "columns": [...]}``;
            inspect the error and retry with corrected SQL.
        """

        return _table_extraction(state, table_id, sql)

    @tool
    def paragraph_extraction(element_id: str, pattern: str) -> dict[str, Any]:
        """
        Search one text-like HTML element using a regex pattern.

        Use this for extracting values from TITLE, SECTION_HEADER, TEXT,
        LIST_ITEM, or CAPTION elements.

        Args:
            element_id: Existing HTML element id, for example ``dp-p-4``.
            pattern: Python regular expression pattern.

        Returns:
            All regex matches with matched text, spans, and evidence ids.
        """

        return _paragraph_extraction(state, element_id, pattern)

    @tool
    def set_field(
        name: str,
        value: Any,
        evidence_ids: list[str],
        status: str = "resolved",
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Set one output field with value and evidence ids.

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
            failure_reason: Required when status is ``failed``.

        Returns:
            The stored field state or validation errors.
        """

        return _set_field(state, name, value, evidence_ids, status, failure_reason)

    @tool
    def finish() -> dict[str, Any]:
        """
        Finish the extraction run.

        Use this only after all required fields have been set either as
        ``resolved`` or ``failed``.

        Returns:
            ``{"ok": true, "errors": []}`` when validation passes. If
            validation fails, returns ``{"ok": false, "errors": [...]}``.
        """

        return _finish(state)

    return [
        overview,
        read_element,
        table_extraction,
        paragraph_extraction,
        set_field,
        finish,
    ]


def _overview(state: Any) -> dict[str, Any]:
    result = {"tree": _read(state, "document").tree}
    _record_action(state, "overview", {}, _summarize_tool_result(result))
    return result


def _read_element(state: Any, element_id: str) -> dict[str, Any]:
    document = _read(state, "document")
    element = document.elements_by_id.get(element_id)
    if element is None:
        result = {"ok": False, "error": f"unknown element id: {element_id}"}
        _record_action(state, "read_element", {"element_id": element_id}, result)
        return result

    if element.type == "TABLE":
        table = document.tables_by_id.get(element_id)
        if table is None:
            result = {"ok": False, "error": f"unknown table id: {element_id}"}
            _record_action(state, "read_element", {"element_id": element_id}, result)
            return result
        _mark_observed(state, [table.table_id])
        result = {
            "id": table.table_id,
            "type": "TABLE",
            "columns": table.columns,
            "header_row_id": table.header_row_id,
            "row_count": len(table.rows),
            "sql_hint": (
                'Use table name data and wrap every column name in double quotes, '
                'for example SELECT "论文题目" FROM data WHERE "作品类型" = '
                "'学术论文'."
            ),
        }
        _record_action(state, "read_element", {"element_id": element_id}, result)
        return result

    _mark_observed(state, [element.id])
    result = {
        "id": element.id,
        "type": element.type,
        "text": element.text,
    }
    _record_action(state, "read_element", {"element_id": element_id}, result)
    return result


def _table_extraction(state: Any, table_id: str, sql: str) -> dict[str, Any]:
    document = _read(state, "document")
    table = document.tables_by_id.get(table_id)
    if table is None:
        result = {"ok": False, "error": f"unknown table id: {table_id}"}
        _record_action(state, "table_extraction", {"table_id": table_id, "sql": sql}, result)
        return result
    if not _is_safe_select(sql):
        result = {"ok": False, "error": "sql must be a single SELECT statement"}
        _record_action(state, "table_extraction", {"table_id": table_id, "sql": sql}, result)
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
            {"table_id": table_id, "sql": sql},
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
    _record_action(state, "table_extraction", {"table_id": table_id, "sql": sql}, _summarize_tool_result(result))
    return result


def _paragraph_extraction(state: Any, element_id: str, pattern: str) -> dict[str, Any]:
    document = _read(state, "document")
    element = document.elements_by_id.get(element_id)
    if element is None:
        result = {"ok": False, "error": f"unknown element id: {element_id}"}
        _record_action(state, "paragraph_extraction", {"element_id": element_id, "pattern": pattern}, result)
        return result
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        result = {"ok": False, "error": f"invalid regex: {exc}"}
        _record_action(state, "paragraph_extraction", {"element_id": element_id, "pattern": pattern}, result)
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
    _record_action(state, "paragraph_extraction", {"element_id": element_id, "pattern": pattern}, _summarize_tool_result(result))
    return result


def _set_field(
    state: Any,
    name: str,
    value: Any,
    evidence_ids: list[str],
    status: str,
    failure_reason: str | None,
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
    }
    _read(state, "field_states")[name] = field_state
    _record_action(
        state,
        "set_field",
        {"name": name, "value": value, "evidence_ids": evidence_ids, "status": status},
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


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _match_row_id(table: Any, values: dict[str, Any]) -> str | None:
    for row_id, row in zip(table.row_ids, table.rows, strict=False):
        if all(str(row.get(column, "")) == str(value) for column, value in values.items()):
            return row_id
    return None


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


__all__ = [
    "build_tools",
    "_overview",
    "_read_element",
    "_table_extraction",
    "_paragraph_extraction",
    "_set_field",
    "_finish",
]
