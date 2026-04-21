from __future__ import annotations

from file_extraction_agent.impl.state import GraphState, build_graph_state
from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    FieldDefinition,
    GraphInput,
    NormalizedDocument,
    ResolvedFieldOutput,
    TaskSpec,
)


def test_build_graph_state_initializes_empty_execution_state():
    graph_input = GraphInput(
        session_id="session-1",
        documents=[NormalizedDocument(document_id="doc-1", markdown="内容")],
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
    assert state.resolved_fields == []
    assert state.warnings == []


def test_graph_state_accepts_prepared_progress_payloads():
    graph_input = GraphInput(
        session_id="session-2",
        documents=[NormalizedDocument(document_id="doc-2", markdown="内容")],
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
        resolved_fields=[
            ResolvedFieldOutput(
                field_name="amount",
                status="resolved",
                final_value="100.00",
                used_field_outputs=["amount"],
                reason="字段已定案",
            )
        ],
        warnings=["字段来源存在轻微歧义"],
    )

    assert state.broad_output is not None
    assert state.resolved_fields[0].field_name == "amount"
    assert state.warnings == ["字段来源存在轻微歧义"]
