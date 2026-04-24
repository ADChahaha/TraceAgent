from __future__ import annotations

from file_extraction_agent.impl.schemas import EvidenceCollection, ExtractionInput, FieldEvidence
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_run_broad_extraction_invokes_client_and_writes_output_to_state():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", text="发票号：INV-100")],
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

