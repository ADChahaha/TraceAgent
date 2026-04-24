from __future__ import annotations

import pytest

from file_extraction_agent.impl.schemas import EvidenceCollection, ExtractionInput, FieldEvidence
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_run_broad_extraction_invokes_client_and_writes_output_to_state():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="发票号：INV-100")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                    required=True,
                )
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-1"],
                evidence_texts=["发票号：INV-100"],
                local_status="evidence_found",
            )
        ]
    )
    seen_call: dict[str, object] = {}

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            seen_call["output_schema"] = output_schema
            seen_call["messages"] = messages
            return evidence_collection

    returned_state = run_broad_extraction(
        state=state,
        extractor_client=FakeExtractorClient(),
    )

    assert returned_state is state
    assert state.evidence_collection is evidence_collection
    assert seen_call["output_schema"] is EvidenceCollection
    assert "invoice_no" in seen_call["messages"][1]["content"]


def test_run_broad_extraction_rejects_missing_task_field():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="发票号：INV-100")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
            ],
        ),
    )
    state = build_graph_state(extraction_input)

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return EvidenceCollection(
                fields=[
                    FieldEvidence(
                        field_name="invoice_no",
                        relevant_block_ids=["b-1"],
                        evidence_texts=["发票号：INV-100"],
                        local_status="evidence_found",
                    )
                ]
            )

    with pytest.raises(ValueError, match="missing broad evidence fields: amount"):
        run_broad_extraction(state=state, extractor_client=FakeExtractorClient())


def test_run_broad_extraction_rejects_duplicate_fields_before_resolution():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="发票号：INV-100")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
        ),
    )
    state = build_graph_state(extraction_input)

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return EvidenceCollection(
                fields=[
                    FieldEvidence(field_name="invoice_no", local_status="evidence_found"),
                    FieldEvidence(field_name="invoice_no", local_status="evidence_found"),
                ]
            )

    with pytest.raises(ValueError, match="duplicate broad evidence fields: invoice_no"):
        run_broad_extraction(state=state, extractor_client=FakeExtractorClient())


def test_run_broad_extraction_rejects_unknown_fields_and_block_references():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="发票号：INV-100")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
        ),
    )
    state = build_graph_state(extraction_input)

    class UnknownFieldClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return EvidenceCollection(
                fields=[
                    FieldEvidence(field_name="invoice_no", local_status="evidence_found"),
                    FieldEvidence(field_name="amount", local_status="evidence_found"),
                ]
            )

    with pytest.raises(ValueError, match="unknown broad evidence fields: amount"):
        run_broad_extraction(state=state, extractor_client=UnknownFieldClient())

    class UnknownBlockClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return EvidenceCollection(
                fields=[
                    FieldEvidence(
                        field_name="invoice_no",
                        relevant_block_ids=["b-missing"],
                        evidence_texts=["发票号：INV-100"],
                        local_status="evidence_found",
                    )
                ]
            )

    with pytest.raises(ValueError, match="unknown broad evidence block ids: b-missing"):
        run_broad_extraction(state=state, extractor_client=UnknownBlockClient())
