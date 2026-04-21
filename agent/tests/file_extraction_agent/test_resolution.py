from __future__ import annotations

from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    FieldDefinition,
    GraphInput,
    NormalizedDocument,
    ResolvedFieldOutput,
    TaskSpec,
)


def _build_graph_input() -> GraphInput:
    return GraphInput(
        session_id="session-resolution",
        documents=[NormalizedDocument(document_id="doc-1", markdown="测试文档")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                    required=True,
                ),
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                    required=True,
                ),
            ],
        ),
    )


def test_resolve_fields_uses_task_spec_order_and_fills_missing_outputs():
    from file_extraction_agent.impl.resolution import resolve_fields

    graph_input = _build_graph_input()
    broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-001"],
                evidence_texts=["发票号：INV-001"],
                local_status="candidate_found",
            )
        ]
    )

    resolved_fields = resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )

    assert [field.field_name for field in resolved_fields] == ["invoice_no", "amount"]
    assert resolved_fields[0] == ResolvedFieldOutput(
        field_name="invoice_no",
        status="resolved",
        final_value="INV-001",
        used_field_outputs=["invoice_no"],
        extra_lookup_used=False,
        reason="候选值唯一，可直接定案",
    )
    assert resolved_fields[1] == ResolvedFieldOutput(
        field_name="amount",
        status="failed",
        used_field_outputs=[],
        extra_lookup_used=False,
        failure_reason="未找到可用候选值",
    )


def test_resolve_fields_deduplicates_same_candidate_before_resolving():
    from file_extraction_agent.impl.resolution import resolve_fields

    graph_input = _build_graph_input()
    broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-002", "INV-002", "INV-002"],
                evidence_texts=["发票号：INV-002"],
                local_status="candidate_found",
            ),
            BroadExtractionFieldOutput(
                field_name="amount",
                candidate_values=["100.00"],
                evidence_texts=["金额：100.00"],
                local_status="candidate_found",
            ),
        ]
    )

    resolved_fields = resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )

    assert resolved_fields[0].status == "resolved"
    assert resolved_fields[0].final_value == "INV-002"


def test_resolve_fields_marks_conflicting_candidates_as_failed():
    from file_extraction_agent.impl.resolution import resolve_fields

    graph_input = _build_graph_input()
    broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-003", "INV-004"],
                evidence_texts=["发票号候选1", "发票号候选2"],
                local_status="candidate_conflict",
            ),
            BroadExtractionFieldOutput(
                field_name="amount",
                candidate_values=["100.00"],
                evidence_texts=["金额：100.00"],
                local_status="candidate_found",
            ),
        ]
    )

    resolved_fields = resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )

    assert resolved_fields[0] == ResolvedFieldOutput(
        field_name="invoice_no",
        status="failed",
        used_field_outputs=["invoice_no"],
        extra_lookup_used=False,
        failure_reason="候选值冲突，暂时无法定案",
    )


def test_run_resolution_reads_broad_output_and_writes_back_to_state():
    from file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_graph_input())
    state.broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-005"],
                evidence_texts=["发票号：INV-005"],
                local_status="candidate_found",
            ),
            BroadExtractionFieldOutput(
                field_name="amount",
                candidate_values=["200.00"],
                evidence_texts=["金额：200.00"],
                local_status="candidate_found",
            ),
        ]
    )

    returned_state = run_resolution(state=state)

    assert returned_state is state
    assert [field.status for field in state.resolved_fields] == ["resolved", "resolved"]
    assert [field.final_value for field in state.resolved_fields] == ["INV-005", "200.00"]
