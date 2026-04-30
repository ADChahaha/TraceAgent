from __future__ import annotations

import pytest

from service.file_extraction_agent.impl.schemas import BroadAction, ExtractionInput
from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def _build_state():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-invoice", text="发票号：INV-100"),
            NormalizedBlock(document_id="doc-1", block_id="b-amount", text="金额：100.00"),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
            ],
        ),
    )
    return build_graph_state(extraction_input)


def test_run_broad_stage_uses_search_add_candidate_and_finish_actions():
    from service.file_extraction_agent.impl.broad.runner import run_broad_stage

    state = _build_state()

    class FakeExtractorClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, *, output_schema, messages, tools=None):
            assert output_schema is BroadAction
            assert tools == ["search_grep", "add_broad_candidate"]
            self.calls += 1
            if self.calls == 1:
                return BroadAction(
                    action="search_grep",
                    field_name="invoice_no",
                    query="发票号",
                )
            if self.calls == 2:
                assert "b-invoice:p:p1" in messages[-1]["content"]
                return BroadAction(
                    action="add_broad_candidate",
                    field_name="invoice_no",
                    refs=["b-invoice:p:p1"],
                    reason="命中发票号段落",
                )
            if self.calls == 3:
                return BroadAction(
                    action="finish_broad",
                    field_name="invoice_no",
                    status="enough_evidence",
                    reason="已有发票号候选",
                )
            if self.calls == 4:
                return BroadAction(
                    action="search_grep",
                    field_name="amount",
                    query="金额",
                )
            if self.calls == 5:
                return BroadAction(
                    action="add_broad_candidate",
                    field_name="amount",
                    refs=["b-amount:p:p1"],
                    reason="命中金额段落",
                )
            return BroadAction(
                action="finish_broad",
                field_name="amount",
                status="enough_evidence",
                reason="已有金额候选",
            )

    returned_state = run_broad_stage(state=state, extractor_client=FakeExtractorClient())

    assert returned_state is state
    assert [item.candidate_id for item in state.candidates["invoice_no"]] == ["c1"]
    assert state.candidates["invoice_no"][0].ref == "b-invoice:p:p1"
    assert state.broad_finishes["invoice_no"].status == "enough_evidence"
    assert [action.action_type for action in state.actions["invoice_no"]] == [
        "search_grep",
        "add_broad_candidate",
        "finish_broad",
    ]


def test_run_broad_stage_rejects_enough_evidence_without_candidates():
    from service.file_extraction_agent.impl.broad.runner import run_broad_loop_for_field

    state = _build_state()
    field = state.extraction_input.task_spec.fields[0]

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, messages, tools
            return BroadAction(
                action="finish_broad",
                field_name="invoice_no",
                status="enough_evidence",
                reason="错误地声称证据充分",
            )

    with pytest.raises(ValueError, match="finish_broad status=enough_evidence requires candidates"):
        run_broad_loop_for_field(
            state=state,
            field=field,
            extractor_client=FakeExtractorClient(),
        )


def test_run_broad_stage_rejects_action_for_another_field():
    from service.file_extraction_agent.impl.broad.runner import run_broad_loop_for_field

    state = _build_state()
    field = state.extraction_input.task_spec.fields[0]

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages, tools=None):
            del output_schema, messages, tools
            return BroadAction(
                action="search_grep",
                field_name="amount",
                query="金额",
            )

    with pytest.raises(ValueError, match="broad action field_name does not match current field"):
        run_broad_loop_for_field(
            state=state,
            field=field,
            extractor_client=FakeExtractorClient(),
        )
