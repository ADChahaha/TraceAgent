from __future__ import annotations

import json

from file_extraction_agent.impl import prompts
from file_extraction_agent.schemas import (
    BroadExtractionFieldOutput,
    BroadExtractionOutput,
    FieldDefinition,
    GraphInput,
    NormalizedBlock,
    NormalizedDocument,
    ResolvedFieldOutput,
    TaskSpec,
)


def test_build_broad_extraction_messages_includes_session_task_and_documents_summary():
    graph_input = GraphInput(
        session_id="session-1",
        documents=[
            NormalizedDocument(
                document_id="doc-1",
                markdown="发票号码：INV-001",
                md_list=["发票号码：INV-001"],
                blocks=[
                    NormalizedBlock(
                        text="发票号码：INV-001",
                        page_no=1,
                        meta_info={"block_id": "b-1"},
                    )
                ],
            )
        ],
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
        metadata={"source": "backend"},
    )

    messages = prompts.build_broad_extraction_messages(graph_input)

    assert messages[0]["role"] == "system"
    assert "BroadExtractionOutput" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["session_id"] == "session-1"
    assert payload["task_name"] == "invoice"
    assert payload["metadata"] == {"source": "backend"}
    assert payload["documents"][0]["document_id"] == "doc-1"
    assert payload["documents"][0]["markdown"] == "发票号码：INV-001"
    assert payload["documents"][0]["md_list"] == ["发票号码：INV-001"]
    assert payload["documents"][0]["blocks"][0]["text"] == "发票号码：INV-001"
    assert payload["fields"][0]["field_name"] == "invoice_no"


def test_build_field_resolution_messages_focuses_on_target_field_and_candidates():
    graph_input = GraphInput(
        session_id="session-2",
        documents=[NormalizedDocument(document_id="doc-2", markdown="金额：100.00")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
            ],
        ),
    )
    broad_output = BroadExtractionOutput(
        fields=[
            BroadExtractionFieldOutput(
                field_name="amount",
                candidate_values=["100.00"],
                evidence_texts=["金额：100.00"],
                local_status="candidate_found",
            ),
            BroadExtractionFieldOutput(
                field_name="invoice_no",
                candidate_values=["INV-002"],
                evidence_texts=["发票号：INV-002"],
                local_status="candidate_found",
            ),
        ]
    )

    messages = prompts.build_field_resolution_messages(
        graph_input=graph_input,
        target_field_name="amount",
        broad_output=broad_output,
    )

    assert messages[0]["role"] == "system"
    assert "ResolvedFieldOutput" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["session_id"] == "session-2"
    assert payload["target_field_name"] == "amount"
    assert payload["target_field"]["field_name"] == "amount"
    assert payload["target_field"]["candidate_values"] == ["100.00"]
    assert [field["field_name"] for field in payload["all_field_outputs"]] == [
        "amount",
        "invoice_no",
    ]

