from __future__ import annotations

from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec
from service.file_extraction_agent.impl.schemas import ExtractionInput


def _build_state():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-text", text="应付金额：100.00 元", page_no=1),
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                kind="table",
                text="| room | status |\n|---|---|\n| A101 | selected |\n| A102 | rejected |",
                page_no=2,
            ),
        ],
        task_spec=TaskSpec(
            task_name="room-selection",
            fields=[FieldDefinition(field_name="amount", display_name="金额", type="money")],
        ),
    )
    return build_graph_state(extraction_input)


def test_search_text_grep_returns_paragraph_refs_and_records_action():
    from service.file_extraction_agent.impl.tools.search import search_text_grep

    state = _build_state()

    results = search_text_grep(state=state, field_name="amount", query="应付金额")

    assert [item.ref for item in results] == ["b-text:p:p1"]
    assert results[0].text == "应付金额：100.00 元"
    assert state.actions["amount"][0].action_type == "text_grep"
    assert state.actions["amount"][0].refs == ["b-text:p:p1"]


def test_search_table_rows_grep_returns_only_matching_row_refs():
    from service.file_extraction_agent.impl.tools.search import search_table_rows_grep

    state = _build_state()

    results = search_table_rows_grep(state=state, field_name="amount", query="selected")

    assert [item.ref for item in results] == ["b-table:r:r1"]
    assert results[0].text == "room=A101 | status=selected"
    assert "A102" not in results[0].text
    assert state.actions["amount"][0].action_type == "table_row_grep"


def test_search_grep_searches_text_and_table_rows_with_or_query():
    from service.file_extraction_agent.impl.tools.search import search_grep

    state = _build_state()

    results = search_grep(
        state=state,
        field_name="amount",
        query="应付金额 OR selected",
    )

    assert [item.ref for item in results] == ["b-text:p:p1", "b-table:r:r1"]
    assert state.actions["amount"][0].action_type == "search_grep"
    assert state.actions["amount"][0].refs == ["b-text:p:p1", "b-table:r:r1"]
    assert state.actions["amount"][0].metadata["query_terms"] == ["应付金额", "selected"]


def test_search_grep_only_splits_terms_with_uppercase_or_format():
    from service.file_extraction_agent.impl.tools.search import search_grep

    state = _build_state()

    results = search_grep(
        state=state,
        field_name="amount",
        query="应付金额 或 selected",
    )

    assert results == []
    assert state.actions["amount"][0].metadata["query_terms"] == ["应付金额 或 selected"]


def test_candidate_tools_add_dedupe_and_read_field_candidates():
    from service.file_extraction_agent.impl.tools.candidates import (
        add_broad_candidate,
        add_resolution_candidate,
        get_candidate_bundle,
    )

    state = _build_state()

    broad_candidates = add_broad_candidate(
        state=state,
        field_name="amount",
        refs=["b-text:p:p1"],
        reason="broad 命中金额段落",
    )
    repeated_candidates = add_broad_candidate(
        state=state,
        field_name="amount",
        refs=["b-text:p:p1"],
        reason="重复写入应复用已有候选",
    )
    resolution_candidates = add_resolution_candidate(
        state=state,
        field_name="amount",
        refs=["b-table:r:r1"],
        reason="resolution 二次补充表格行",
    )
    bundle = get_candidate_bundle(state=state, field_name="amount")

    assert [candidate.candidate_id for candidate in broad_candidates] == ["c1"]
    assert [candidate.candidate_id for candidate in repeated_candidates] == ["c1"]
    assert [candidate.candidate_id for candidate in resolution_candidates] == ["c2"]
    assert [candidate.ref for candidate in bundle] == ["b-text:p:p1", "b-table:r:r1"]
    assert [action.action_type for action in state.actions["amount"]] == [
        "add_broad_candidate",
        "add_broad_candidate",
        "add_resolution_candidate",
        "get_candidate_bundle",
    ]
