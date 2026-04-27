from __future__ import annotations

from file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    ExtractionInput,
    FieldDecision,
    FieldEvidence,
)
from file_extraction_agent.impl.state import GraphState, build_graph_state
from file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_build_graph_state_initializes_empty_execution_state():
    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="内容")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                )
            ],
        ),
    )

    state = build_graph_state(extraction_input)

    assert isinstance(state, GraphState)
    assert state.extraction_input.task_spec == extraction_input.task_spec
    assert state.extraction_input.blocks[0].block_id == "b-1"
    assert state.evidence_collection is None
    assert state.field_decisions == []
    assert state.warnings == []


def test_build_graph_state_rejects_blocks_without_block_id():
    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", text="内容")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                )
            ],
        ),
    )

    try:
        build_graph_state(extraction_input)
    except ValueError as exc:
        assert "block_id is required" in str(exc)
    else:
        raise AssertionError("graph state 不应为缺失 block_id 的输入兜底")


def test_graph_state_accepts_prepared_progress_payloads():
    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-2", block_id="b-2", text="内容")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                )
            ],
        ),
    )

    state = GraphState(
        extraction_input=extraction_input,
        evidence_collection=EvidenceCollection(fields=[]),
        field_decisions=[
            FieldDecision(
                field_name="amount",
                status="resolved",
                value="100.00",
                evidence=FieldEvidence(field_name="amount", local_status="evidence_found"),
                reason="字段已定案",
            )
        ],
        warnings=["字段来源存在轻微歧义"],
    )

    assert state.evidence_collection is not None
    assert state.field_decisions[0].field_name == "amount"
    assert state.field_decisions[0].reason == "字段已定案"
    assert state.warnings == ["字段来源存在轻微歧义"]
