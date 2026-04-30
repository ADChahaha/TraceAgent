from __future__ import annotations

import pytest

from service.file_extraction_agent.impl.schemas import (
    ExtractionInput,
    FieldResolutionAction,
)
from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.impl.tools.candidates import add_broad_candidate
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def _build_state():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-invoice", text="发票号：INV-001"),
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                kind="table",
                text="| room | status |\n|---|---|\n| A101 | selected |",
            ),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
                FieldDefinition(field_name="selected_room", display_name="选中房间", type="string"),
            ],
        ),
    )
    return build_graph_state(extraction_input)


def test_run_resolution_stage_final_decision_must_reference_candidate_ids():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()
    add_broad_candidate(
        state=state,
        field_name="invoice_no",
        refs=["b-invoice:p:p1"],
        reason="broad 已找到发票号候选",
    )
    add_broad_candidate(
        state=state,
        field_name="selected_room",
        refs=["b-table:r:r1"],
        reason="broad 已找到表格候选",
    )

    class FakeExtractorClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, *, output_schema, messages, tools=None):
            assert output_schema is FieldResolutionAction
            assert tools == [
                "get_candidate_bundle",
                "search_grep",
                "add_resolution_candidate",
            ]
            self.calls += 1
            if self.calls == 1:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                    candidate_ids=["c1"],
                    related_fields=["invoice_no"],
                    reason="候选证据支持字段值",
                )
            return FieldResolutionAction(
                action="final_decision",
                field_name="selected_room",
                status="resolved",
                value="A101",
                candidate_ids=["c1"],
                reason="表格候选行支持字段值",
            )

    returned_state = run_resolution_stage(state=state, extractor_client=FakeExtractorClient())

    assert returned_state is state
    assert state.field_decisions["invoice_no"].value == "INV-001"
    assert state.field_decisions["invoice_no"].candidate_ids == ["c1"]
    assert state.field_decisions["selected_room"].value == "A101"
    assert state.actions["invoice_no"][-1].action_type == "final_decision"


def test_run_resolution_stage_rejects_unknown_candidate_ids():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_loop_for_field

    state = _build_state()
    field = state.extraction_input.task_spec.fields[0]

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, messages, tools
            return FieldResolutionAction(
                action="final_decision",
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
                candidate_ids=["missing-candidate"],
                reason="引用了不存在的候选",
            )

    with pytest.raises(ValueError, match="unknown candidate_ids: missing-candidate"):
        run_resolution_loop_for_field(
            state=state,
            field=field,
            extractor_client=FakeExtractorClient(),
        )


def test_run_resolution_stage_can_search_and_add_resolution_candidate_before_decision():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_loop_for_field

    state = _build_state()
    field = state.extraction_input.task_spec.fields[1]

    class FakeExtractorClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, tools
            self.calls += 1
            if self.calls == 1:
                return FieldResolutionAction(
                    action="search_grep",
                    field_name="selected_room",
                    query="selected",
                )
            if self.calls == 2:
                assert "b-table:r:r1" in messages[-1]["content"]
                return FieldResolutionAction(
                    action="add_resolution_candidate",
                    field_name="selected_room",
                    refs=["b-table:r:r1"],
                    reason="二次检索找到选中房间行",
                )
            return FieldResolutionAction(
                action="final_decision",
                field_name="selected_room",
                status="resolved",
                value="A101",
                candidate_ids=["c1"],
                reason="resolution 候选支持字段值",
            )

    decision = run_resolution_loop_for_field(
        state=state,
        field=field,
        extractor_client=FakeExtractorClient(),
    )

    assert decision.value == "A101"
    assert decision.candidate_ids == ["c1"]
    assert state.candidates["selected_room"][0].source_stage == "resolution"
    assert [action.action_type for action in state.actions["selected_room"]] == [
        "search_grep",
        "add_resolution_candidate",
        "final_decision",
    ]


def test_run_resolution_stage_records_candidate_bundle_reads():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_loop_for_field

    state = _build_state()
    field = state.extraction_input.task_spec.fields[0]
    add_broad_candidate(
        state=state,
        field_name="invoice_no",
        refs=["b-invoice:p:p1"],
        reason="broad 已找到候选",
    )

    class FakeExtractorClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, tools
            self.calls += 1
            if self.calls == 1:
                return FieldResolutionAction(
                    action="get_candidate_bundle",
                    field_name="invoice_no",
                )
            assert "candidate_id" in messages[-1]["content"]
            return FieldResolutionAction(
                action="final_decision",
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
                candidate_ids=["c1"],
                reason="候选池支持字段值",
            )

    run_resolution_loop_for_field(
        state=state,
        field=field,
        extractor_client=FakeExtractorClient(),
    )

    assert [action.action_type for action in state.actions["invoice_no"]] == [
        "add_broad_candidate",
        "get_candidate_bundle",
        "final_decision",
    ]
