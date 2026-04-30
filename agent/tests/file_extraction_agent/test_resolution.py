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
                "count_field_candidates",
            ]
            self.calls += 1
            if self.calls == 1:
                assert "invoice_no" in messages[1]["content"]
                assert "selected_room" in messages[1]["content"]
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                    candidate_ids=["c1"],
                    related_fields=["invoice_no"],
                    reason="候选证据支持字段值",
                )
            if self.calls == 2:
                return FieldResolutionAction(
                    action="count_field_candidates",
                    field_name="selected_room",
                    source_field_name="selected_room",
                    reason="统计已写入的房间候选数量",
                )
            assert messages[-1]["content"] == "1"
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
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, tools
            return FieldResolutionAction(
                action="final_decision",
                field_name="invoice_no",
                status="resolved",
                value="INV-001",
                candidate_ids=["missing-candidate"],
                reason="引用了不存在的候选",
            )

    with pytest.raises(ValueError, match="unknown candidate_ids: missing-candidate"):
        run_resolution_stage(
            state=state,
            extractor_client=FakeExtractorClient(),
        )


def test_run_resolution_stage_can_search_and_add_resolution_candidate_before_decision():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()

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
            if self.calls == 3:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="selected_room",
                    status="resolved",
                    value="A101",
                    candidate_ids=["c1"],
                    reason="resolution 候选支持字段值",
                )
            if self.calls == 4:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="invoice_no",
                    status="failed",
                    failure_reason="本测试不处理发票号",
                )
            return FieldResolutionAction(
                action="final_decision",
                field_name="invoice_no",
                status="failed",
                failure_reason="本测试不处理发票号",
            )

    run_resolution_stage(
        state=state,
        extractor_client=FakeExtractorClient(),
    )
    decision = state.field_decisions["selected_room"]

    assert decision.value == "A101"
    assert decision.candidate_ids == ["c1"]
    assert state.candidates["selected_room"][0].source_stage == "resolution"
    assert [action.action_type for action in state.actions["selected_room"]] == [
        "search_grep",
        "add_resolution_candidate",
        "final_decision",
    ]


def test_run_resolution_stage_returns_tool_error_for_unknown_ref_and_continues():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()

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
                return FieldResolutionAction(
                    action="add_resolution_candidate",
                    field_name="selected_room",
                    refs=["b-table:r:r999"],
                    reason="误用了不存在的 ref",
                )
            if self.calls == 3:
                assert "tool_error" in messages[-1]["content"]
                assert "unknown evidence ref" in messages[-1]["content"]
                return FieldResolutionAction(
                    action="add_resolution_candidate",
                    field_name="selected_room",
                    refs=["b-table:r:r1"],
                    reason="改用 search_grep 返回的合法 ref",
                )
            if self.calls == 4:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="selected_room",
                    status="resolved",
                    value="A101",
                    candidate_ids=["c1"],
                    reason="合法候选支持字段值",
                )
            return FieldResolutionAction(
                action="final_decision",
                field_name="invoice_no",
                status="failed",
                failure_reason="本测试不处理发票号",
            )

    run_resolution_stage(state=state, extractor_client=FakeExtractorClient())

    assert state.field_decisions["selected_room"].value == "A101"
    assert [action.action_type for action in state.actions["selected_room"]] == [
        "search_grep",
        "tool_error",
        "add_resolution_candidate",
        "final_decision",
    ]


def test_run_resolution_stage_records_candidate_bundle_reads():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()
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
            if self.calls == 2:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                    candidate_ids=["c1"],
                    reason="候选池支持字段值",
                )
            return FieldResolutionAction(
                action="final_decision",
                field_name="selected_room",
                status="failed",
                failure_reason="本测试不处理房间",
            )

    run_resolution_stage(
        state=state,
        extractor_client=FakeExtractorClient(),
    )

    assert [action.action_type for action in state.actions["invoice_no"]] == [
        "add_broad_candidate",
        "get_candidate_bundle",
        "final_decision",
    ]


def test_run_resolution_stage_requires_model_final_decision_after_count_tool():
    from service.file_extraction_agent.impl.resolution.runner import run_resolution_stage

    state = _build_state()
    add_broad_candidate(
        state=state,
        field_name="invoice_no",
        refs=["b-invoice:p:p1"],
        reason="来源字段候选",
    )

    class FakeExtractorClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, tools
            self.calls += 1
            if self.calls == 1:
                return FieldResolutionAction(
                    action="final_decision",
                    field_name="invoice_no",
                    status="resolved",
                    value="INV-001",
                    candidate_ids=["c1"],
                    reason="来源字段定案",
                )
            if self.calls == 2:
                return FieldResolutionAction(
                    action="count_field_candidates",
                    field_name="invoice_no",
                    reason="数量字段由来源字段候选数量派生",
                )
            if self.calls == 3:
                assert messages[-1]["content"] == "1"
                return FieldResolutionAction(
                    action="add_resolution_candidate",
                    field_name="selected_room",
                    values=["1"],
                    reason="把 count_field_candidates 返回的数字写入数量字段候选池",
                )
            assert "candidate_id" in messages[-1]["content"]
            return FieldResolutionAction(
                action="final_decision",
                field_name="selected_room",
                status="resolved",
                value=1,
                candidate_ids=["c1"],
                related_fields=["invoice_no"],
                reason="模型基于 count_field_candidates 明确定案数量字段",
            )

    run_resolution_stage(state=state, extractor_client=FakeExtractorClient())

    decision = state.field_decisions["selected_room"]
    assert decision.status == "resolved"
    assert decision.value == 1
    assert decision.candidate_ids == ["c1"]
    assert decision.related_fields == ["invoice_no"]
    assert [action.action_type for action in state.actions["selected_room"]] == [
        "add_resolution_candidate",
        "final_decision",
    ]
    assert state.actions["invoice_no"][-1].action_type == "count_field_candidates"
