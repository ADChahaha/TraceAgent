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
MAX_READ_SECTION_HTML_CHARS = 12_000
MAX_INLINE_EVIDENCE_PREVIEW = 40
TABLE_AUDIT_BLANK_ROW_ID_LIMIT = 10
INLINE_TEXT_TYPES = {"TITLE", "SECTION_HEADER", "TEXT", "CAPTION"}

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
    def update_soft_plan(plan: list[dict[str, str]]) -> dict[str, Any]:
        """
        Replace the soft replay plan with the model's current local work plan.

        Use this as a lightweight, human-readable work log. A soft plan is not
        a field checklist, a hard state machine, or an evidence ledger. It
        should show the current document-understanding stages: what evidence
        area is being read, which related field group may be resolved, and what
        remains pending. Call it before starting a new local work unit and when
        plan status changes enough to help frontend replay.

        Each item must contain:
        - ``step``: a compact stage-like title.
        - ``status``: ``pending``, ``in_progress``, or ``completed``.

        The full list you pass replaces the previous soft plan. Keep useful
        completed steps when they help the reader understand the path, but
        avoid growing the plan into a long transcript.

        Args:
            plan: Ordered soft-plan items. Each item needs ``step`` and
                ``status``.

        Returns:
            The stored soft plan, with 1-based ``plan_index`` values added.
        """

        return _update_soft_plan(state, plan)

    @tool
    def overview() -> dict[str, Any]:
        """
        Return section headers and same-level block items in document order.

        Use this to choose a section or block scope before reading content. The
        overview includes section containers, headings, paragraphs, lists, and
        tables, each with model-friendly metadata. A paragraph, list, or table
        that is a sibling of a heading is returned as its own item, not as part
        of the previous heading. It does not return table rows or expanded list
        items.

        Returns:
            A compact list of sections and same-level block items.
        """

        return _overview(state)

    @tool
    def read_section(section_id: str, reason: str) -> dict[str, Any]:
        """
        Read block previews for a heading's real descendants.

        Use this after overview has identified a heading id. It only reads
        block previews that are actual DOM descendants of that heading. Sibling
        paragraphs, lists, and tables are separate overview items; read those
        by their own id or through a parent section container. Use read_blocks
        to read full blocks, read_list for paged list items, and query_table
        for SQL over a table block.

        Args:
            section_id: Existing heading id.
            reason: Why this section is needed for the current field.

        Returns:
            Section title plus block offsets, block ids, types, and previews.
        """

        return _read_section(state, section_id, reason=reason)

    @tool
    def read_blocks(section_id: str, indexes: list[int], reason: str) -> dict[str, Any]:
        """
        Read selected block indexes from a section container, heading, or leaf block id.

        Use this after overview or read_section has shown block indexes and
        previews. Pass the exact zero-based indexes you need as a list. Use this
        for targeted evidence blocks, especially non-contiguous indexes. For a
        contiguous range, prefer read_block_range. Section containers are read
        by index over their DOM-order descendants. Headings only expose actual
        DOM descendants, not following siblings. Leaf block ids can be used as a
        one-block scope with indexes=[0]. List and table blocks are returned as
        refs instead of fully expanded structures; use read_list or query_table
        for those.

        Args:
            section_id: Existing section container, heading, or leaf block id.
            indexes: Zero-based selected block indexes inside that scope.
            reason: Why these blocks are needed for the current field.

        Returns:
            HTML-like block content and observed evidence ids.
        """

        return _read_blocks(state, section_id, indexes, reason=reason)

    @tool
    def read_block_range(section_id: str, start_index: int, count: int, reason: str) -> dict[str, Any]:
        """
        Read a contiguous range of blocks from a section container, heading, or leaf block id.

        Use this after overview or read_section has shown block indexes and you
        need to scan neighboring context in order. It reads ``count`` blocks
        starting at zero-based ``start_index`` from the same ordered scope.
        Use read_blocks instead when you already know the exact selected
        indexes or need non-contiguous evidence blocks. List and table blocks
        are returned as refs instead of fully expanded structures; use read_list or
        query_table for those.

        Args:
            section_id: Existing section container, heading, or leaf block id.
            start_index: Zero-based first block index inside that scope.
            count: Number of consecutive blocks to read.
            reason: Why this contiguous range is needed for the current field.

        Returns:
            HTML-like block content and observed evidence ids.
        """

        return _read_block_range(state, section_id, start_index, count, reason=reason)

    @tool
    def read_list(section_id: str, block_offset: int, item_offset: int, number: int, reason: str) -> dict[str, Any]:
        """
        Read list items from a list block or top-level list id.

        Use this when read_section, read_blocks, or read_block_range shows that
        a block offset is a list. If overview returns a top-level list id, pass
        that id as section_id with block_offset=0. Items are paged by item
        offset so long lists do not flood the context.

        Args:
            section_id: Existing section, section container, or top-level list id.
            block_offset: Zero-based block offset of the list inside the section.
                Use 0 when section_id is already the list id.
            item_offset: Zero-based list item offset.
            number: Number of list items to read.
            reason: Why these list items are needed for the current field.

        Returns:
            Full list item text and observed evidence ids.
        """

        return _read_list(state, section_id, block_offset, item_offset, number, reason=reason)

    @tool
    def query_table(section_id: str, block_offset: int, sql: str, reason: str) -> dict[str, Any]:
        """
        Query a table block by scope offset or top-level table id using SQL.

        Use this when read_section, read_blocks, or read_block_range shows that
        a block offset is a table. If overview returns a top-level table id,
        pass that id as section_id with block_offset=0. The SQL must be a single
        SELECT statement over table name data. All SQL column names must be
        wrapped in double quotes.

        Args:
            section_id: Existing section, section container, or top-level table id.
            block_offset: Zero-based block offset of the table inside the scope.
                Use 0 when section_id is already the table id.
            sql: A single SELECT statement over table name ``data``.
            reason: Why this table query is needed for the current field.

        Returns:
            Matching table rows, evidence ids, lightweight table_audit, and query summary.
            Rows contain only the selected SQL cells. Blank selected cells are
            returned as empty strings in row values. Use summary for returned
            row count and selected-output blank counts; use table_audit for
            whole-table blank-cell background.
        """

        return _query_table(state, section_id, block_offset, sql, reason=reason)

    @tool
    def preview_inline_evidence(source_id: str, start_index: int, count: int, reason: str) -> dict[str, Any]:
        """
        Preview inline evidence ids from an already-read text block.

        Only use this after reading a text block with read_blocks,
        read_block_range, search/scan results, or another text-reading tool,
        and only when you are ready to make evidence precise for set_field.
        This tool splits the source text into sentence-like inline candidates
        and returns inline_id values. Use those inline_id values, not the whole
        paragraph or heading id, in set_field evidence_ids for text evidence.
        Do not use this for tables or lists: use row ids from query_table for
        tables and item ids from read_list for lists.

        Args:
            source_id: Observed text-like element id to refine into inline evidence.
            start_index: Zero-based first inline candidate to preview.
            count: Number of inline candidates to preview.
            reason: Why this inline evidence is needed for the current field.

        Returns:
            Inline evidence candidates and observed inline evidence ids.
        """

        return _preview_inline_evidence(state, source_id, start_index, count, reason=reason)

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
        ``status="failed"`` when the field cannot be completed reliably and
        needs human review. Null is a valid resolved value when the declared
        field type is null, or when an enum variant declares a null payload.
        Do not use status failed just because value is null, absent, negative,
        or an allowed enum variant represents no mention. Call set_field as
        soon as enough evidence for the current field has been observed; do not
        keep reading unrelated elements first.

        Use this only after this same run has observed the supporting evidence
        through ``read_blocks``, ``read_block_range``, ``read_list``,
        ``query_table``, or ``preview_inline_evidence``. Do not call this from
        document overview alone.

        Resolved evidence must be precise. Text values need inline ids returned
        by preview_inline_evidence; do not use whole paragraph, heading, or
        caption ids. Tables need row ids returned by query_table; a table id by
        itself is not enough. Lists need item ids returned by read_list; a list
        container id by itself is not enough.

        Args:
            name: Field name declared in task_spec.
            value: Extracted field value. Use null when the declared field type
                or selected enum variant type is ``null``; use null with
                ``status="failed"`` only when no reliable value can be set.
            evidence_ids: Observed ids supporting the value, such as
                ``["dp-p-4::inline-0"]``, ``["dp-table-1", "dp-tr-2"]``, or
                ``["dp-ul-1", "dp-li-2"]``.
            status: ``resolved`` when a valid value, including a declared null
                value, is set; ``failed`` only when the field needs human
                review because it cannot be completed reliably.
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
        update_soft_plan,
        overview,
        read_section,
        read_blocks,
        read_block_range,
        read_list,
        query_table,
        preview_inline_evidence,
        set_field,
        finish,
    ]


def _overview(state: Any) -> dict[str, Any]:
    document = _read(state, "document")
    result = {
        "sections": _section_overview(document),
        "items": _outline_items(document),
    }
    _record_action(state, "overview", {}, _summarize_tool_result(result))
    return result


def _update_soft_plan(state: Any, plan: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    normalized_plan: list[dict[str, Any]] = []
    if not isinstance(plan, list):
        errors.append({"message": "plan must be a list"})
    else:
        for index, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                errors.append({"message": "plan item must be an object", "plan_index": index})
                continue
            step = str(item.get("step") or "").strip()
            status = str(item.get("status") or "").strip()
            if not step:
                errors.append({"message": "plan item step is required", "plan_index": index})
            if status not in {"pending", "in_progress", "completed"}:
                errors.append(
                    {
                        "message": "plan item status must be pending, in_progress, or completed",
                        "plan_index": index,
                        "status": status,
                    }
                )
            if step and status in {"pending", "in_progress", "completed"}:
                normalized_plan.append(
                    {
                        "plan_index": index,
                        "step": step,
                        "status": status,
                    }
                )
    if errors:
        result = {"ok": False, "errors": errors}
        _record_action(state, "update_soft_plan", {"plan": plan}, result)
        return result

    setattr(state, "soft_plan", normalized_plan)
    statuses = {item["plan_index"]: dict(item) for item in normalized_plan}
    setattr(state, "plan_statuses", statuses)
    result = {"ok": True, "plan": normalized_plan}
    _record_action(state, "update_soft_plan", {"plan": plan}, result)
    return result


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
                'such as SELECT "column_name" FROM data WHERE "filter_column" = '
                "'value'."
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


def _search_elements(state: Any, query: str, limit: int = 10, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    normalized_query = " ".join(str(query or "").split())
    try:
        max_results = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        max_results = 10
    if not normalized_query:
        result = {"ok": False, "error": "query must be a non-empty string"}
        _record_action(state, "search_elements", _args_with_reason({"query": query, "limit": limit}, reason), result)
        return result

    query_folded = normalized_query.casefold()
    matches: list[dict[str, Any]] = []
    for element in document.elements_by_id.values():
        if element.type not in {"TITLE", "SECTION_HEADER", "TEXT", "LIST_ITEM", "CAPTION"}:
            continue
        if _is_page_level_aggregate_id(element.id):
            continue
        text = str(element.text or "")
        index = text.casefold().find(query_folded)
        if index < 0:
            continue
        matches.append(
            {
                "element_id": element.id,
                "type": element.type,
                "html": _element_html(document, element),
                "evidence_ids": [element.id],
                "snippet": _snippet(text, index, len(normalized_query)),
                "text_chars": len(text),
            }
        )
        if len(matches) >= max_results:
            break

    _mark_observed(state, [evidence_id for match in matches for evidence_id in match["evidence_ids"]])
    result = {
        "query": normalized_query,
        "limit": max_results,
        "matches": matches,
        "match_count": len(matches),
        "truncated": len(matches) >= max_results,
        "note": "Search results include readable HTML and observed evidence_ids; call read_element only if more local context is needed.",
    }
    _record_action(state, "search_elements", _args_with_reason({"query": normalized_query, "limit": max_results}, reason), result)
    return result


def _is_page_level_aggregate_id(element_id: str) -> bool:
    return re.fullmatch(r"page_\d+", str(element_id or "")) is not None


def _has_ancestor(document: Any, element: Any, ancestor_id: str) -> bool:
    parent_id = getattr(element, "parent_id", None)
    while parent_id:
        if parent_id == ancestor_id:
            return True
        parent = document.elements_by_id.get(parent_id)
        if parent is None:
            return False
        parent_id = getattr(parent, "parent_id", None)
    return False




def _read_section(state: Any, section_id: str, *, reason: str | None = None) -> dict[str, Any]:
    document = _read(state, "document")
    section = _section_element(document, section_id)
    if isinstance(section, dict):
        result = section
        _record_action(state, "read_section", _args_with_reason({"section_id": section_id}, reason), result)
        return result

    blocks = [_block_preview(document, block) for block in _section_blocks(document, section)]
    result = {
        "section_id": section_id,
        "title": section.text,
        "level": _section_heading_level(section.tag),
        "blocks": blocks,
        "evidence_ids": [],
    }
    _record_action(state, "read_section", _args_with_reason({"section_id": section_id}, reason), _summarize_tool_result(result))
    return result


def _read_blocks(
    state: Any,
    section_id: str,
    indexes: list[int],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    document = _read(state, "document")
    section = _scope_element(document, section_id)
    if isinstance(section, dict):
        result = section
        _record_action(state, "read_blocks", _args_with_reason({"section_id": section_id, "indexes": indexes}, reason), result)
        return result
    blocks = _scope_blocks(document, section)
    normalized_indexes = _normalize_block_indexes(indexes, len(blocks))
    if isinstance(normalized_indexes, dict):
        result = normalized_indexes
        _record_action(state, "read_blocks", _args_with_reason({"section_id": section_id, "indexes": indexes}, reason), result)
        return result
    selected = [blocks[index] for index in normalized_indexes]
    rendered = [_block_read_result(document, block) for block in selected]
    evidence_ids = [block["block_id"] for block in rendered]
    _mark_observed(state, evidence_ids)
    result = {
        "section_id": section_id,
        "indexes": normalized_indexes,
        "blocks": rendered,
        "evidence_ids": evidence_ids,
    }
    _record_action(state, "read_blocks", _args_with_reason({"section_id": section_id, "indexes": normalized_indexes}, reason), _summarize_tool_result(result))
    return result


def _read_block_range(
    state: Any,
    section_id: str,
    start_index: int,
    count: int,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    document = _read(state, "document")
    section = _scope_element(document, section_id)
    args = {"section_id": section_id, "start_index": start_index, "count": count}
    if isinstance(section, dict):
        result = section
        _record_action(state, "read_block_range", _args_with_reason(args, reason), result)
        return result
    blocks = _scope_blocks(document, section)
    normalized_range = _normalize_block_range(start_index, count, len(blocks))
    if isinstance(normalized_range, dict):
        result = normalized_range
        _record_action(state, "read_block_range", _args_with_reason(args, reason), result)
        return result
    start, bounded_count = normalized_range
    selected = blocks[start : start + bounded_count]
    rendered = [_block_read_result(document, block) for block in selected]
    evidence_ids = [block["block_id"] for block in rendered]
    indexes = [block["offset"] for block in selected]
    _mark_observed(state, evidence_ids)
    result = {
        "section_id": section_id,
        "start_index": start,
        "count": len(selected),
        "indexes": indexes,
        "blocks": rendered,
        "evidence_ids": evidence_ids,
    }
    _record_action(
        state,
        "read_block_range",
        _args_with_reason({"section_id": section_id, "start_index": start, "count": len(selected)}, reason),
        _summarize_tool_result(result),
    )
    return result


def _read_list(
    state: Any,
    section_id: str,
    block_offset: int,
    item_offset: int,
    number: int,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    document = _read(state, "document")
    list_block = _scope_block_at(document, section_id, block_offset)
    if isinstance(list_block, dict):
        result = list_block
        _record_action(state, "read_list", _args_with_reason({"section_id": section_id, "block_offset": block_offset, "item_offset": item_offset, "number": number}, reason), result)
        return result
    if list_block.tag not in {"ul", "ol"}:
        result = {"ok": False, "error": f"block offset is not a list: {block_offset}"}
        _record_action(state, "read_list", _args_with_reason({"section_id": section_id, "block_offset": block_offset, "item_offset": item_offset, "number": number}, reason), result)
        return result
    item_ids = _list_item_ids(document, list_block.id)
    start = _bounded_offset(item_offset, len(item_ids))
    count = _bounded_number(number)
    selected_ids = item_ids[start : start + count]
    items = []
    for index, item_id in enumerate(selected_ids, start=start):
        element = document.elements_by_id[item_id]
        items.append(
            {
                "item_offset": index,
                "item_id": item_id,
                "text": element.text,
                "html": f'<item id="{_attr(item_id)}">{_text(element.text)}</item>',
            }
        )
    evidence_ids = [list_block.id, *selected_ids]
    _mark_observed(state, evidence_ids)
    result = {
        "section_id": section_id,
        "block_offset": block_offset,
        "list_id": list_block.id,
        "item_offset": start,
        "number": count,
        "items": items,
        "evidence_ids": evidence_ids,
    }
    _record_action(state, "read_list", _args_with_reason({"section_id": section_id, "block_offset": block_offset, "item_offset": start, "number": count}, reason), _summarize_tool_result(result))
    return result


def _query_table(
    state: Any,
    section_id: str,
    block_offset: int,
    sql: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    document = _read(state, "document")
    table_block = _scope_block_at(document, section_id, block_offset)
    if isinstance(table_block, dict):
        result = table_block
        _record_action(state, "query_table", _args_with_reason({"section_id": section_id, "block_offset": block_offset, "sql": sql}, reason), result)
        return result
    if table_block.type != "TABLE":
        result = {"ok": False, "error": f"block offset is not a table: {block_offset}"}
        _record_action(state, "query_table", _args_with_reason({"section_id": section_id, "block_offset": block_offset, "sql": sql}, reason), result)
        return result
    result = _table_extraction(state, table_block.id, sql, reason=reason)
    result = {**result, "section_id": section_id, "block_offset": block_offset}
    if getattr(state, "actions", None) and state.actions[-1].get("tool_name") == "table_extraction":
        state.actions[-1] = {
            "tool_name": "query_table",
            "args": _args_with_reason({"section_id": section_id, "block_offset": block_offset, "sql": sql}, reason),
            "result": _summarize_tool_result(result),
        }
    return result


def _preview_inline_evidence(
    state: Any,
    source_id: str,
    start_index: int,
    count: int,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    document = _read(state, "document")
    normalized_source_id = str(source_id or "").strip()
    args = {
        "source_id": source_id,
        "start_index": start_index,
        "count": count,
    }
    source = document.elements_by_id.get(normalized_source_id)
    if source is None:
        result = {"ok": False, "error": f"unknown source id: {normalized_source_id}"}
        _record_action(state, "preview_inline_evidence", _args_with_reason(args, reason), result)
        return result
    if not _is_inline_text_source(source):
        result = {
            "ok": False,
            "error": "source_id must be a text-like element; use query_table for tables and read_list for lists",
            "source_id": normalized_source_id,
        }
        _record_action(state, "preview_inline_evidence", _args_with_reason(args, reason), result)
        return result
    if normalized_source_id not in _read(state, "observed_evidence_ids", set()):
        result = {
            "ok": False,
            "error": "source_id must be observed before preview_inline_evidence",
            "source_id": normalized_source_id,
        }
        _record_action(state, "preview_inline_evidence", _args_with_reason(args, reason), result)
        return result

    candidates = _inline_evidence_candidates(source)
    normalized_range = _normalize_inline_range(start_index, count, len(candidates))
    if isinstance(normalized_range, dict):
        result = normalized_range
        _record_action(state, "preview_inline_evidence", _args_with_reason(args, reason), result)
        return result

    start, bounded_count = normalized_range
    selected = candidates[start : start + bounded_count]
    _remember_inline_evidence(state, selected)
    evidence_ids = [candidate["inline_id"] for candidate in selected]
    _mark_observed(state, evidence_ids)
    result = {
        "source_id": normalized_source_id,
        "source_type": source.type,
        "start_index": start,
        "count": len(selected),
        "total_inline_count": len(candidates),
        "inline_evidence": selected,
        "evidence_ids": evidence_ids,
        "truncated": start + len(selected) < len(candidates),
        "note": "Use inline_id values in set_field evidence_ids for text evidence.",
    }
    _record_action(
        state,
        "preview_inline_evidence",
        _args_with_reason({"source_id": normalized_source_id, "start_index": start, "count": len(selected)}, reason),
        _summarize_tool_result(result),
    )
    return result


def _read_section_auto_scan_query(section: Any, reason: str | None, section_id: str) -> str:
    parts = [
        str(reason or "").strip(),
        str(getattr(section, "text", "") or "").strip(),
    ]
    query = " ".join(part for part in parts if part)
    return query or section_id


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

    table_audit = _table_audit(table)
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
                'Wrap every column name in double quotes, such as '
                'SELECT "column_name" FROM data WHERE "filter_column" = \'value\'.'
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
    output_columns = [column for column in selected_columns if column != "__row_id"]
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
        "columns": output_columns,
        "rows": rows,
        "table_audit": table_audit,
        "summary": _table_query_summary(rows, output_columns),
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
    field_def = _field_defs_by_name(state)[name]

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
    granularity_errors = _resolved_evidence_granularity_errors(state, evidence_ids) if status == "resolved" else []
    if granularity_errors:
        return {"ok": False, "errors": [{"field": name, **error} for error in granularity_errors]}
    value_error = _field_value_error(field_def, value) if status == "resolved" else None
    if value_error:
        return {"ok": False, "errors": [{"field": name, **value_error}]}

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


def _resolved_evidence_granularity_errors(state: Any, evidence_ids: list[str]) -> list[dict[str, Any]]:
    document = _read(state, "document")
    evidence_set = set(evidence_ids)
    errors: list[dict[str, Any]] = []

    text_block_ids = [
        evidence_id
        for evidence_id in evidence_ids
        if _is_coarse_text_evidence_id(document, evidence_id)
    ]
    if text_block_ids:
        errors.append(
            {
                "message": "text evidence must use inline evidence ids from preview_inline_evidence",
                "ids": text_block_ids,
            }
        )

    table_ids = [
        evidence_id
        for evidence_id in evidence_ids
        if _is_table_container_evidence_id(document, evidence_id)
        and not _has_row_evidence_for_table(document, evidence_id, evidence_set)
    ]
    if table_ids:
        errors.append(
            {
                "message": "table evidence must include row ids from query_table",
                "ids": table_ids,
            }
        )

    list_ids = [
        evidence_id
        for evidence_id in evidence_ids
        if _is_list_container_evidence_id(document, evidence_id)
        and not _has_item_evidence_for_list(document, evidence_id, evidence_set)
    ]
    if list_ids:
        errors.append(
            {
                "message": "list evidence must include item ids from read_list",
                "ids": list_ids,
            }
        )

    return errors


def _is_coarse_text_evidence_id(document: Any, evidence_id: str) -> bool:
    element = document.elements_by_id.get(evidence_id)
    if element is None:
        return False
    if element.tag in {"ul", "ol", "li", "table", "tr", "figure"}:
        return False
    return element.type in INLINE_TEXT_TYPES


def _is_table_container_evidence_id(document: Any, evidence_id: str) -> bool:
    element = document.elements_by_id.get(evidence_id)
    return bool(element and element.type == "TABLE")


def _has_row_evidence_for_table(document: Any, table_id: str, evidence_ids: set[str]) -> bool:
    for evidence_id in evidence_ids:
        row = document.row_index.get(evidence_id)
        if row and row.get("table_id") == table_id:
            return True
    return False


def _is_list_container_evidence_id(document: Any, evidence_id: str) -> bool:
    element = document.elements_by_id.get(evidence_id)
    return bool(element and element.tag in {"ul", "ol"})


def _has_item_evidence_for_list(document: Any, list_id: str, evidence_ids: set[str]) -> bool:
    for evidence_id in evidence_ids:
        element = document.elements_by_id.get(evidence_id)
        if element and element.tag == "li" and element.parent_id == list_id:
            return True
    return False


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
            if not field_state.get("evidence_ids") and not _allows_empty_resolved_evidence(field_def, field_state.get("value")):
                errors.append({"field": name, "message": "resolved field requires evidence"})
            value_error = _field_value_error(field_def, field_state.get("value"))
            if value_error:
                errors.append({"field": name, **value_error})
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
    return (
        evidence_id in document.elements_by_id
        or evidence_id in document.row_index
        or evidence_id in _inline_evidence_store(state)
    )


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


def _inline_evidence_store(state: Any) -> dict[str, dict[str, Any]]:
    store = _read(state, "inline_evidence_by_id", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        setattr(state, "inline_evidence_by_id", store)
    except Exception:
        return {}
    return store


def _remember_inline_evidence(state: Any, candidates: list[dict[str, Any]]) -> None:
    store = _inline_evidence_store(state)
    for candidate in candidates:
        inline_id = str(candidate.get("inline_id") or "")
        if inline_id:
            store[inline_id] = dict(candidate)


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


def _table_audit(table: Any) -> dict[str, Any]:
    rows = _read(table, "rows", []) or []
    columns = _read(table, "columns", []) or []
    row_ids = _read(table, "row_ids", []) or []

    by_column = []
    for column in columns:
        blank_row_ids = [
            row_id
            for row_id, row in zip(row_ids, rows, strict=False)
            if not str(row.get(column, "")).strip()
        ]
        if blank_row_ids:
            by_column.append(
                {
                    "column": column,
                    "blank_count": len(blank_row_ids),
                    "blank_row_ids": blank_row_ids[:TABLE_AUDIT_BLANK_ROW_ID_LIMIT],
                }
            )

    repeated_header_rows = [
        row_id
        for row_id, row in zip(row_ids, rows, strict=False)
        if columns and all(str(row.get(column, "")).strip() == str(column).strip() for column in columns)
    ]

    return {
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "blank_cells": {
            "total_blank_cell_count": sum(item["blank_count"] for item in by_column),
            "by_column": by_column,
        },
        "structure_signals": [
            {
                "code": "repeated_header_row",
                "row_ids": repeated_header_rows,
            }
        ] if repeated_header_rows else [],
    }


def _table_query_summary(rows: list[dict[str, Any]], selected_columns: list[str]) -> str:
    row_count = len(rows)
    parts = [f"返回 {row_count} 行"]
    for column in selected_columns:
        empty_count = sum(
            1
            for row in rows
            if not str((row.get("values") or {}).get(column, "")).strip()
        )
        parts.append(f"输出列“{column}”空值 {empty_count}/{row_count} 行")
    return "；".join(parts) + "。"


def _heading_level(tag: str) -> int | None:
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return int(tag[1])
    return None


def _section_heading_level(tag: str) -> int | None:
    if tag in {"h1", "h2", "h3"}:
        return int(tag[1])
    return None


def _section_element(document: Any, section_id: str) -> Any:
    section = document.elements_by_id.get(section_id)
    if section is None:
        return {"ok": False, "error": f"unknown section id: {section_id}"}
    if _section_heading_level(section.tag) is None:
        return {"ok": False, "error": f"element is not a section heading: {section_id}"}
    return section


def _section_overview(document: Any) -> list[dict[str, Any]]:
    return [
        {
            "section_id": element.id,
            "title": element.text,
            "level": _section_heading_level(element.tag),
            "block_count": len(_section_blocks(document, element)),
            "subsections": [],
        }
        for element in document.elements_by_id.values()
        if _section_heading_level(element.tag) is not None
    ]


def _outline_items(document: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for element in document.elements_by_id.values():
        if element.tag in {"tr", "caption"} or _is_list_child(document, element):
            continue

        item_type, read_with = _outline_item_type_and_reader(element)
        if item_type is None:
            continue

        item: dict[str, Any] = {
            "item_id": element.id,
            "type": item_type,
            "tag": element.tag,
            "read_with": read_with,
            "parent_section_id": "",
        }
        if item_type in {"TITLE", "SECTION_HEADER", "TEXT", "SECTION"}:
            item["preview"] = _first_sentence(element.text)
        if item_type == "LIST":
            item_ids = _list_item_ids(document, element.id)
            item["block_offset"] = 0
            item["item_count"] = len(item_ids)
            item["preview"] = [
                _first_sentence(document.elements_by_id[item_id].text)
                for item_id in item_ids[:3]
            ]
        if item_type == "TABLE":
            table = document.tables_by_id.get(element.id)
            item["block_offset"] = 0
            item["columns"] = table.columns if table else []
            item["row_count"] = len(table.rows) if table else 0
            if table and table.label:
                item["label"] = table.label
        items.append(item)
    return items


def _outline_item_type_and_reader(element: Any) -> tuple[str | None, str | None]:
    if element.tag == "section":
        return "SECTION", "read_blocks"
    if element.tag == "h1":
        return "TITLE", "read_section"
    if element.tag in {"h2", "h3", "h4", "h5", "h6"}:
        return "SECTION_HEADER", "read_section"
    if element.tag == "p":
        return "TEXT", "read_blocks"
    if element.tag in {"ul", "ol"}:
        return "LIST", "read_list"
    if element.tag == "table" or (element.tag == "figure" and element.type == "TABLE"):
        return "TABLE", "query_table"
    if element.type == "TABLE":
        return "TABLE", "query_table"
    return None, None


def _section_blocks(document: Any, section: Any) -> list[dict[str, Any]]:
    ordered = list(document.elements_by_id.values())
    blocks: list[dict[str, Any]] = []
    for element in ordered:
        if element.id == section.id:
            continue
        if not _has_ancestor(document, element, section.id):
            continue
        if not _is_section_block(document, element):
            continue
        blocks.append({"offset": len(blocks), "element": element})
    return blocks


def _is_section_block(document: Any, element: Any) -> bool:
    if element.tag in {"tr", "caption"} or _is_list_child(document, element):
        return False
    if _section_heading_level(element.tag) is not None:
        return False
    return element.tag in {"section", "p", "ul", "ol", "table", "figure", "h4", "h5", "h6"} or element.type in {
        "SECTION",
        "TEXT",
        "TABLE",
        "TITLE",
        "SECTION_HEADER",
    }


def _scope_element(document: Any, scope_id: str) -> Any:
    scope = document.elements_by_id.get(scope_id)
    if scope is None:
        return {"ok": False, "error": f"unknown scope id: {scope_id}"}
    return scope


def _scope_blocks(document: Any, scope: Any) -> list[dict[str, Any]]:
    if scope.tag == "section":
        ordered = list(document.elements_by_id.values())
        blocks: list[dict[str, Any]] = []
        for element in ordered:
            if element.id == scope.id:
                continue
            if not _has_ancestor(document, element, scope.id):
                continue
            if not _is_scope_block(document, element):
                continue
            blocks.append({"offset": len(blocks), "element": element})
        return blocks
    if _section_heading_level(scope.tag) is not None:
        return _section_blocks(document, scope)
    if _is_leaf_block_scope(scope):
        return [{"offset": 0, "element": scope}]
    return []


def _scope_block_at(document: Any, scope_id: str, block_offset: int) -> Any:
    scope = _scope_element(document, scope_id)
    if isinstance(scope, dict):
        return scope
    blocks = _scope_blocks(document, scope)
    try:
        index = int(block_offset)
    except (TypeError, ValueError):
        return {"ok": False, "error": "block_offset must be an integer"}
    if index < 0 or index >= len(blocks):
        return {"ok": False, "error": f"block_offset outside scope: {block_offset}"}
    return blocks[index]["element"]


def _normalize_block_indexes(indexes: Any, block_count: int) -> list[int] | dict[str, Any]:
    if not isinstance(indexes, list) or not indexes:
        return {"ok": False, "error": "indexes must be a non-empty list"}

    normalized: list[int] = []
    for raw_index in indexes:
        if isinstance(raw_index, bool):
            return {"ok": False, "error": "indexes must contain integers"}
        if isinstance(raw_index, int):
            index = raw_index
        elif isinstance(raw_index, str) and re.fullmatch(r"[+-]?\d+", raw_index.strip()):
            index = int(raw_index)
        else:
            return {"ok": False, "error": "indexes must contain integers"}
        if index < 0 or index >= block_count:
            return {"ok": False, "error": f"index outside scope: {raw_index}", "block_count": block_count}
        normalized.append(index)
    return normalized


def _normalize_block_range(start_index: Any, count: Any, block_count: int) -> tuple[int, int] | dict[str, Any]:
    start = _parse_range_integer(start_index)
    if start is None:
        return {"ok": False, "error": "start_index must be a non-negative integer"}
    if start < 0:
        return {"ok": False, "error": "start_index must be a non-negative integer"}
    requested_count = _parse_range_integer(count)
    if requested_count is None:
        return {"ok": False, "error": "count must be a positive integer"}
    if requested_count <= 0:
        return {"ok": False, "error": "count must be a positive integer"}
    if start >= block_count:
        return {"ok": False, "error": f"start_index outside scope: {start_index}", "block_count": block_count}
    bounded_count = min(requested_count, 20, block_count - start)
    return start, bounded_count


def _normalize_inline_range(start_index: Any, count: Any, inline_count: int) -> tuple[int, int] | dict[str, Any]:
    start = _parse_range_integer(start_index)
    if start is None or start < 0:
        return {"ok": False, "error": "start_index must be a non-negative integer"}
    requested_count = _parse_range_integer(count)
    if requested_count is None or requested_count <= 0:
        return {"ok": False, "error": "count must be a positive integer"}
    if inline_count == 0:
        return 0, 0
    if start >= inline_count:
        return {"ok": False, "error": f"start_index outside inline evidence: {start_index}", "inline_count": inline_count}
    bounded_count = min(requested_count, MAX_INLINE_EVIDENCE_PREVIEW, inline_count - start)
    return start, bounded_count


def _parse_range_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value)
    return None


def _is_scope_block(document: Any, element: Any) -> bool:
    if element.tag in {"tr", "caption"} or _is_list_child(document, element):
        return False
    return element.tag in {"section", "p", "ul", "ol", "table", "figure", "h1", "h2", "h3", "h4", "h5", "h6"} or element.type in {
        "SECTION",
        "TEXT",
        "TABLE",
        "TITLE",
        "SECTION_HEADER",
    }


def _is_leaf_block_scope(scope: Any) -> bool:
    return scope.tag in {"p", "ul", "ol", "table", "figure"} or scope.type in {"TEXT", "TABLE"}


def _block_preview(document: Any, block: dict[str, Any]) -> dict[str, Any]:
    element = block["element"]
    result: dict[str, Any] = {
        "offset": block["offset"],
        "block_id": element.id,
        "type": _block_type(document, element),
    }
    if result["type"] == "TABLE":
        table = document.tables_by_id.get(element.id)
        result["columns"] = table.columns if table else []
        result["row_count"] = len(table.rows) if table else 0
        if table and table.label:
            result["label"] = table.label
    elif result["type"] == "LIST":
        item_ids = _list_item_ids(document, element.id)
        result["item_count"] = len(item_ids)
        result["preview"] = [
            _first_sentence(document.elements_by_id[item_id].text)
            for item_id in item_ids[:3]
        ]
    else:
        result["preview"] = _first_sentence(element.text)
    return result


def _block_read_result(document: Any, block: dict[str, Any]) -> dict[str, Any]:
    element = block["element"]
    block_type = _block_type(document, element)
    result: dict[str, Any] = {
        "offset": block["offset"],
        "block_id": element.id,
        "type": block_type,
    }
    if block_type == "LIST":
        result["html"] = _list_ref_html(document, element.id, preview_limit=2)
    else:
        result["html"] = _element_html(document, element)
    return result


def _block_type(document: Any, element: Any) -> str:
    if element.type == "TABLE":
        return "TABLE"
    if element.tag in {"ul", "ol"}:
        return "LIST"
    return element.type


def _is_inline_text_source(element: Any) -> bool:
    if element.tag in {"ul", "ol", "li", "table", "tr", "figure"}:
        return False
    return element.type in INLINE_TEXT_TYPES


def _inline_evidence_candidates(element: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for inline_index, span in enumerate(_inline_text_spans(str(element.text or ""))):
        start, end, text = span
        candidates.append(
            {
                "inline_id": f"{element.id}::inline-{inline_index}",
                "inline_index": inline_index,
                "source_id": element.id,
                "text": text,
                "char_start": start,
                "char_end": end,
            }
        )
    return candidates


def _inline_text_spans(text: str) -> list[tuple[int, int, str]]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"[。！？!?]|(?<!\d)\.(?!\d)", normalized):
        end = match.end()
        if end > start:
            spans.append((start, end))
        start = end
    if start < len(normalized):
        spans.append((start, len(normalized)))

    return [
        (
            start + len(normalized[start:end]) - len(normalized[start:end].lstrip()),
            end - (len(normalized[start:end]) - len(normalized[start:end].rstrip())),
            normalized[start:end].strip(),
        )
        for start, end in spans
        if normalized[start:end].strip()
    ]


def _section_block_at(document: Any, section_id: str, block_offset: int) -> Any:
    section = _section_element(document, section_id)
    if isinstance(section, dict):
        return section
    blocks = _section_blocks(document, section)
    try:
        index = int(block_offset)
    except (TypeError, ValueError):
        return {"ok": False, "error": "block_offset must be an integer"}
    if index < 0 or index >= len(blocks):
        return {"ok": False, "error": f"block_offset outside section: {block_offset}"}
    return blocks[index]["element"]


def _bounded_offset(value: int, length: int) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(offset, length))


def _bounded_number(value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(number, 20))


def _first_sentence(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    match = re.search(r".*?[。！？.!?](?=\s|$|[^0-9])", normalized)
    if match:
        return match.group(0)
    return normalized


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
    text = str(item.get("text", ""))
    return [f'{indent}<{tag} id="{_attr(item_id)}">{_text(text)}</{tag}>']


def _list_ref_html_lines(document: Any, list_id: str, indent: str) -> list[str]:
    item_ids = _list_item_ids(document, list_id)
    lines = [f'{indent}<list-ref id="{_attr(list_id)}" items="{_attr(len(item_ids))}">']
    for item_id in item_ids:
        element = document.elements_by_id[item_id]
        lines.append(
            f'{indent}  <item-ref id="{_attr(item_id)}">{_text(element.text)}</item-ref>'
        )
    lines.append(f"{indent}</list-ref>")
    return lines


def _list_ref_html(document: Any, list_id: str, *, preview_limit: int = 2) -> str:
    item_ids = _list_item_ids(document, list_id)
    lines = [f'<list-ref id="{_attr(list_id)}" items="{_attr(len(item_ids))}">']
    for item_id in item_ids[: max(0, preview_limit)]:
        element = document.elements_by_id[item_id]
        lines.append(
            f'  <item-ref id="{_attr(item_id)}">{_text(element.text)}</item-ref>'
        )
    if len(item_ids) > preview_limit:
        lines.append(f'  <more-items remaining="{_attr(len(item_ids) - preview_limit)}" />')
    lines.append("</list-ref>")
    return "\n".join(lines)


def _list_item_ids(document: Any, list_id: str) -> list[str]:
    return [
        element.id
        for element in document.elements_by_id.values()
        if element.parent_id == list_id and element.tag == "li"
    ]


def _element_tag(document: Any, element_id: str) -> str:
    element = document.elements_by_id.get(element_id)
    return element.tag if element else ""


def _is_list_child(document: Any, element: Any) -> bool:
    if element.tag != "li" or not element.parent_id:
        return False
    return _element_tag(document, element.parent_id) in {"ul", "ol"}


def _html_like_tag(element: Any) -> str:
    element_type = element["type"] if isinstance(element, dict) else element.type
    if element_type == "SECTION":
        return "section"
    if element_type == "TITLE":
        return "title"
    if element_type == "SECTION_HEADER":
        return "heading"
    if element_type == "LIST_ITEM":
        return "item"
    if element_type == "CAPTION":
        return "caption"
    return "text"


def _snippet(text: str, index: int, match_length: int, *, context_chars: int = 80) -> str:
    start = max(0, index - context_chars)
    end = min(len(text), index + match_length + context_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


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
    if field_type == "null":
        return value is None
    return False


def _field_value_error(field_def: Any, value: Any) -> dict[str, Any] | None:
    field_type = _read(field_def, "type", "string")
    if field_type == "enum":
        return _enum_value_error(field_def, value)
    if not _value_matches_type(value, field_type):
        return {
            "message": "field value does not match type",
            "expected_type": field_type,
        }
    return None


def _enum_value_error(field_def: Any, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("variant"), str) or "value" not in value:
        return {"message": "enum value must be an object with variant and value"}
    variant_name = value["variant"]
    variant = _enum_variant_by_name(field_def).get(variant_name)
    if variant is None:
        return {
            "message": "enum variant is not declared",
            "variant": variant_name,
        }
    variant_type = _read(variant, "type", "null")
    if not _value_matches_type(value.get("value"), variant_type):
        return {
            "message": "enum payload does not match variant type",
            "variant": variant_name,
            "expected_type": variant_type,
        }
    return None


def _enum_variant_by_name(field_def: Any) -> dict[str, Any]:
    return {
        str(_read(variant, "name")): variant
        for variant in (_read(field_def, "variants", []) or [])
        if _read(variant, "name")
    }


def _allows_empty_resolved_evidence(field_def: Any, value: Any) -> bool:
    if _read(field_def, "type", "string") != "enum" or not isinstance(value, dict):
        return False
    variant = _enum_variant_by_name(field_def).get(str(value.get("variant")))
    return variant is not None and _read(variant, "type", "null") == "null" and value.get("value") is None


def _args_with_reason(args: dict[str, Any], reason: str | None) -> dict[str, Any]:
    if reason is None:
        return args
    return {**args, "reason": reason}


__all__ = [
    "build_tools",
    "_overview",
    "_update_soft_plan",
    "_search_elements",
    "_read_element",
    "_read_section",
    "_read_blocks",
    "_read_block_range",
    "_read_list",
    "_query_table",
    "_preview_inline_evidence",
    "_table_extraction",
    "_paragraph_extraction",
    "_set_field",
    "_finish",
]
