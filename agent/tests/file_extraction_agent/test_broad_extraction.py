from __future__ import annotations

from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    FieldDefinition,
    GraphInput,
    NormalizedDocument,
    TaskSpec,
)


def test_run_broad_extraction_invokes_client_and_writes_output_to_state():
    from file_extraction_agent.impl.broad_extraction import run_broad_extraction

    graph_input = GraphInput(
        session_id="session-broad",
        documents=[NormalizedDocument(document_id="doc-1", markdown="发票号：INV-100")],
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
    state = build_graph_state(graph_input)
    broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-100"],
                evidence_texts=["发票号：INV-100"],
                local_status="candidate_found",
            )
        ]
    )
    seen_call: dict[str, object] = {}

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            seen_call["output_schema"] = output_schema
            seen_call["messages"] = messages
            return broad_output

    returned_state = run_broad_extraction(
        state=state,
        extractor_client=FakeExtractorClient(),
    )

    assert returned_state is state
    assert state.broad_output is broad_output
    assert seen_call["output_schema"] is BroadExtractionOutput
    assert "session-broad" in seen_call["messages"][1]["content"]

