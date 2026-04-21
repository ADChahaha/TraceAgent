from __future__ import annotations

from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    ExtractionResult,
    FieldDefinition,
    GraphInput,
    NormalizedDocument,
    TaskSpec,
)


def _build_graph_input() -> GraphInput:
    return GraphInput(
        session_id="session-graph",
        documents=[NormalizedDocument(document_id="doc-1", markdown="发票号：INV-900")],
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
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-900"],
                evidence_texts=["发票号：INV-900"],
                local_status="candidate_found",
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
    assert result.broad_output is broad_output
    assert result.run_trace.rounds == 1
    assert result.run_trace.warnings == ["resolution-ran"]


def test_run_extraction_graph_returns_resolved_fields_from_final_state(monkeypatch):
    from file_extraction_agent.impl import graph as graph_module

    graph_input = _build_graph_input()

    def fake_run_broad_extraction(*, state, extractor_client):
        del extractor_client
        state.broad_output = BroadExtractionOutput(
            fields=[
                BroadExtractionFieldOutput(
                    field_name="invoice_no",
                    candidate_values=["INV-901"],
                    evidence_texts=["发票号：INV-901"],
                    local_status="candidate_found",
                ),
                BroadExtractionFieldOutput(
                    field_name="amount",
                    candidate_values=["300.00"],
                    evidence_texts=["金额：300.00"],
                    local_status="candidate_found",
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

    assert [field.field_name for field in result.resolved_fields] == [
        "invoice_no",
        "amount",
    ]
    assert [field.status for field in result.resolved_fields] == [
        "resolved",
        "resolved",
    ]
    assert [field.final_value for field in result.resolved_fields] == [
        "INV-901",
        "300.00",
    ]
