from __future__ import annotations

from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    BroadTrace,
    ExtractionResult,
    FieldDefinition,
    FieldEvidenceBundle,
    FieldTraceRecord,
    GraphInput,
    NormalizedBlock,
    ResolvedFieldResult,
    TaskSpec,
)


def _build_graph_input() -> GraphInput:
    return GraphInput(
        blocks=[NormalizedBlock(document_id="doc-1", text="发票号：INV-900")],
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


def test_run_extraction_graph_runs_broad_extraction_then_resolution(monkeypatch):
    from file_extraction_agent.impl import graph as graph_module

    graph_input = _build_graph_input()
    broad_output = BroadExtractionOutput(
        fields=[
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-1"],
                evidence_texts=["发票号：INV-900"],
                local_status="evidence_found",
            )
        ]
    )
    call_order: list[str] = []

    def fake_run_broad_extraction(*, state, extractor_client):
        del extractor_client
        call_order.append("broad")
        state.broad_output = broad_output
        return state

    def fake_run_resolution(*, state):
        call_order.append("resolution")
        assert state.broad_output is broad_output
        state.result_fields = [
            ResolvedFieldResult(
                field_name="invoice_no",
                status="resolved",
                final_value="发票号：INV-900",
            )
        ]
        state.trace_fields = [
            FieldTraceRecord(
                field_name="invoice_no",
                status="resolved",
                broad_trace=BroadTrace(local_status="evidence_found"),
                reason="测试 graph 汇总",
            )
        ]
        state.warnings.append("resolution-ran")
        return state

    monkeypatch.setattr(
        graph_module,
        "run_broad_extraction",
        fake_run_broad_extraction,
    )
    monkeypatch.setattr(graph_module, "run_resolution", fake_run_resolution)

    result = graph_module.run_extraction_graph(
        graph_input=graph_input,
        extractor_client=object(),
    )

    assert call_order == ["broad", "resolution"]
    assert isinstance(result, ExtractionResult)
    assert result.result.fields[0].field_name == "invoice_no"
    assert result.trace.warnings == ["resolution-ran"]


def test_run_extraction_graph_returns_result_and_trace_from_final_state(monkeypatch):
    from file_extraction_agent.impl import graph as graph_module

    graph_input = _build_graph_input()

    def fake_run_broad_extraction(*, state, extractor_client):
        del extractor_client
        state.broad_output = BroadExtractionOutput(
            fields=[
                FieldEvidenceBundle(
                    field_name="invoice_no",
                    relevant_block_ids=["b-2"],
                    evidence_texts=["发票号：INV-901"],
                    local_status="evidence_found",
                ),
                FieldEvidenceBundle(
                    field_name="amount",
                    relevant_block_ids=["b-3"],
                    evidence_texts=["金额：300.00"],
                    local_status="evidence_found",
                ),
            ]
        )
        return state

    monkeypatch.setattr(
        graph_module,
        "run_broad_extraction",
        fake_run_broad_extraction,
    )

    result = graph_module.run_extraction_graph(
        graph_input=graph_input,
        extractor_client=object(),
    )

    assert [field.field_name for field in result.result.fields] == [
        "invoice_no",
        "amount",
    ]
    assert [field.status for field in result.result.fields] == [
        "resolved",
        "resolved",
    ]
    assert [field.final_value for field in result.result.fields] == [
        "发票号：INV-901",
        "金额：300.00",
    ]
    assert result.trace.fields[0].broad_trace.relevant_block_ids == ["b-2"]
