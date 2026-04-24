from __future__ import annotations

from file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    ExtractionInput,
    FieldDecision,
    FieldEvidence,
)
from file_extraction_agent.schemas import (
    EvidenceSummary,
    ExtractionResult,
    FieldDefinition,
    NormalizedBlock,
    TaskSpec,
)


def _build_extraction_input() -> ExtractionInput:
    return ExtractionInput(
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

    extraction_input = _build_extraction_input()
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
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
        state.evidence_collection = evidence_collection
        return state

    def fake_run_resolution(*, state, extractor_client):
        assert extractor_client == "fake-client"
        call_order.append("resolution")
        assert state.evidence_collection is evidence_collection
        state.field_decisions = [
            FieldDecision(
                field_name="invoice_no",
                status="resolved",
                value="发票号：INV-900",
                evidence=FieldEvidence(field_name="invoice_no", local_status="evidence_found"),
                reason="测试 graph 汇总",
            )
        ]
        state.warnings.append("resolution-ran")
        return state

    monkeypatch.setattr(graph_module, "run_broad_extraction", fake_run_broad_extraction)
    monkeypatch.setattr(graph_module, "run_resolution", fake_run_resolution)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    assert call_order == ["broad", "resolution"]
    assert isinstance(result, ExtractionResult)
    assert result.result.fields[0].field_name == "invoice_no"
    assert result.trace.warnings == ["resolution-ran"]


def test_run_extraction_graph_maps_internal_decisions_to_external_result(monkeypatch):
    from file_extraction_agent.impl import graph as graph_module

    extraction_input = _build_extraction_input()

    def fake_run_broad_extraction(*, state, extractor_client):
        del extractor_client
        state.evidence_collection = EvidenceCollection(
            fields=[
                FieldEvidence(
                    field_name="invoice_no",
                    relevant_block_ids=["b-2"],
                    evidence_texts=["发票号：INV-901"],
                    local_status="evidence_found",
                ),
                FieldEvidence(
                    field_name="amount",
                    relevant_block_ids=["b-3"],
                    evidence_texts=["金额：300.00"],
                    local_status="evidence_found",
                ),
            ]
        )
        return state

    def fake_run_resolution(*, state, extractor_client):
        assert extractor_client == "fake-client"
        state.field_decisions = [
            FieldDecision(
                field_name="invoice_no",
                status="resolved",
                value="发票号：INV-901",
                evidence=FieldEvidence(
                    field_name="invoice_no",
                    relevant_block_ids=["b-2"],
                    evidence_texts=["发票号：INV-901"],
                    local_status="evidence_found",
                ),
                reason="第一条证据可用",
            ),
            FieldDecision(
                field_name="amount",
                status="resolved",
                value="金额：300.00",
                evidence=FieldEvidence(
                    field_name="amount",
                    relevant_block_ids=["b-3"],
                    evidence_texts=["金额：300.00"],
                    local_status="evidence_found",
                ),
                reason="第一条证据可用",
            ),
        ]
        return state

    monkeypatch.setattr(graph_module, "run_broad_extraction", fake_run_broad_extraction)
    monkeypatch.setattr(graph_module, "run_resolution", fake_run_resolution)

    result = graph_module.run_extraction_graph(
        extraction_input=extraction_input,
        extractor_client="fake-client",
    )

    assert [field.field_name for field in result.result.fields] == ["invoice_no", "amount"]
    assert [field.value for field in result.result.fields] == ["发票号：INV-901", "金额：300.00"]
    assert isinstance(result.trace.fields[0].evidence, EvidenceSummary)
    assert result.trace.fields[0].evidence.block_ids == ["b-2"]
