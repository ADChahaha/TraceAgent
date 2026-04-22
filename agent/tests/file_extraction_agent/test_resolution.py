from __future__ import annotations

from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    FieldDefinition,
    FieldEvidenceBundle,
    GraphInput,
    NormalizedBlock,
    TaskSpec,
)


def _build_graph_input() -> GraphInput:
    return GraphInput(
        blocks=[NormalizedBlock(document_id="doc-1", text="测试文档")],
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
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-1"],
                evidence_texts=["发票号：INV-001"],
                local_status="evidence_found",
            )
        ]
    )

    result_fields, trace_fields = resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )

    assert [field.field_name for field in result_fields] == ["invoice_no", "amount"]
    assert result_fields[0].status == "resolved"
    assert result_fields[0].final_value == "发票号：INV-001"
    assert result_fields[1].status == "failed"
    assert trace_fields[0].broad_trace.relevant_block_ids == ["b-1"]
    assert trace_fields[1].failure_reason == "未找到可用证据"


def test_resolve_fields_keeps_broad_trace_separate_from_result():
    from file_extraction_agent.impl.resolution import resolve_fields

    graph_input = _build_graph_input()
    broad_output = BroadExtractionOutput(
        fields=[
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-2"],
                evidence_texts=["发票号：INV-002"],
                local_status="evidence_found",
                local_notes=["字段证据来自表格"],
            ),
            FieldEvidenceBundle(
                field_name="amount",
                relevant_block_ids=["b-3"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
        ]
    )

    result_fields, trace_fields = resolve_fields(
        task_spec=graph_input.task_spec,
        broad_output=broad_output,
    )

    assert result_fields[0].final_value == "发票号：INV-002"
    assert not hasattr(result_fields[0], "relevant_block_ids")
    assert trace_fields[0].broad_trace.local_notes == ["字段证据来自表格"]


def test_run_resolution_reads_broad_output_and_writes_result_and_trace_to_state():
    from file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_graph_input())
    state.broad_output = BroadExtractionOutput(
        fields=[
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-4"],
                evidence_texts=["发票号：INV-005"],
                local_status="evidence_found",
            ),
            FieldEvidenceBundle(
                field_name="amount",
                relevant_block_ids=["b-5"],
                evidence_texts=["金额：200.00"],
                local_status="evidence_found",
            ),
        ]
    )

    returned_state = run_resolution(state=state)

    assert returned_state is state
    assert [field.status for field in state.result_fields] == ["resolved", "resolved"]
    assert [field.final_value for field in state.result_fields] == [
        "发票号：INV-005",
        "金额：200.00",
    ]
    assert [field.broad_trace.relevant_block_ids for field in state.trace_fields] == [
        ["b-4"],
        ["b-5"],
    ]
