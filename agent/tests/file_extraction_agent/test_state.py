from __future__ import annotations

from service.file_extraction_agent.impl.schemas import (
    Candidate,
    ExtractionInput,
    FieldDecision,
    ToolActionRecord,
)
from service.file_extraction_agent.impl.state import GraphState, build_graph_state
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_build_graph_state_initializes_indexes_and_empty_execution_state():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-1", text="发票号：INV-001"),
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
    assert state.blocks_by_id["b-1"].text == "发票号：INV-001"
    assert state.paragraph_index["b-1:p:p1"].text == "发票号：INV-001"
    assert state.table_row_index["b-table:r:r1"].text == "room=A101 | status=selected"
    assert state.candidates == {}
    assert state.broad_finishes == {}
    assert state.field_decisions == {}
    assert state.actions == {}
    assert state.warnings == []


def test_build_graph_state_splits_flattened_markdown_table_rows_with_empty_cells():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-flat-table",
                kind="table",
                text=(
                    "| 楼栋 | 房间 | 平均分 | 模范/文明 | "
                    "|--------|--------|----------|-------------| "
                    "| 18栋 | 212 | 89.92 | 文明寝室 | "
                    "| 18栋 | 213 | 84.00 | | "
                    "| 18栋 | 218 | 98.50 | 模范寝室 |"
                ),
            )
        ],
        task_spec=TaskSpec(
            task_name="civilized_dormitory",
            fields=[
                FieldDefinition(
                    field_name="civilized_dormitory_rooms",
                    display_name="文明寝室房间号",
                    type="string",
                )
            ],
        ),
    )

    state = build_graph_state(extraction_input)

    assert state.table_row_index["b-flat-table:r:r1"].text == (
        "楼栋=18栋 | 房间=212 | 平均分=89.92 | 模范/文明=文明寝室"
    )
    assert state.table_row_index["b-flat-table:r:r2"].text == (
        "楼栋=18栋 | 房间=213 | 平均分=84.00 | 模范/文明="
    )
    assert state.table_row_index["b-flat-table:r:r3"].text == (
        "楼栋=18栋 | 房间=218 | 平均分=98.50 | 模范/文明=模范寝室"
    )


def test_build_graph_state_assumes_input_adapter_already_validated_blocks():
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

    state = build_graph_state(extraction_input)

    assert state.blocks_by_id == {}
    assert state.paragraph_index == {}


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
        candidates={
            "amount": [
                Candidate(
                    candidate_id="c1",
                    field_name="amount",
                    source_stage="broad",
                    ref="b-2:p:p1",
                    text="金额：100.00",
                    reason="命中金额关键词",
                )
            ]
        },
        field_decisions={
            "amount": FieldDecision(
                field_name="amount",
                status="resolved",
                value="100.00",
                candidate_ids=["c1"],
                reason="字段已定案",
            )
        },
        actions={
            "amount": [
                ToolActionRecord(
                    field_name="amount",
                    stage="broad",
                    action_type="add_broad_candidate",
                    refs=["b-2:p:p1"],
                    candidate_ids=["c1"],
                )
            ]
        },
        warnings=["字段来源存在轻微歧义"],
    )

    assert state.candidates["amount"][0].candidate_id == "c1"
    assert state.field_decisions["amount"].reason == "字段已定案"
    assert state.actions["amount"][0].action_type == "add_broad_candidate"
    assert state.warnings == ["字段来源存在轻微歧义"]
