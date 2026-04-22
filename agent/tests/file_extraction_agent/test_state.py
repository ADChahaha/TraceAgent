from __future__ import annotations

from file_extraction_agent.impl.state import GraphState, build_graph_state
from file_extraction_agent.schemas import (
    BroadTrace,
    BroadExtractionOutput,
    FieldDefinition,
    FieldTraceRecord,
    GraphInput,
    NormalizedBlock,
    ResolvedFieldResult,
    TaskSpec,
)


def test_build_graph_state_initializes_empty_execution_state():
    graph_input = GraphInput(
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

    state = build_graph_state(graph_input)

    assert isinstance(state, GraphState)
    assert state.graph_input == graph_input
    assert state.broad_output is None
    assert state.result_fields == []
    assert state.trace_fields == []
    assert state.warnings == []


def test_graph_state_accepts_prepared_progress_payloads():
    graph_input = GraphInput(
        blocks=[NormalizedBlock(document_id="doc-2", text="内容")],
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
        graph_input=graph_input,
        broad_output=BroadExtractionOutput(fields=[]),
        result_fields=[
            ResolvedFieldResult(
                field_name="amount",
                status="resolved",
                final_value="100.00",
            )
        ],
        trace_fields=[
            FieldTraceRecord(
                field_name="amount",
                status="resolved",
                broad_trace=BroadTrace(local_status="evidence_found"),
                used_field_outputs=["amount"],
                reason="字段已定案",
            )
        ],
        warnings=["字段来源存在轻微歧义"],
    )

    assert state.broad_output is not None
    assert state.result_fields[0].field_name == "amount"
    assert state.trace_fields[0].used_field_outputs == ["amount"]
    assert state.warnings == ["字段来源存在轻微歧义"]
