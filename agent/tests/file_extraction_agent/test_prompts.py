from __future__ import annotations

import json

from file_extraction_agent.impl import prompts
from file_extraction_agent.schemas import (
    BroadExtractionOutput,
    FieldDefinition,
    FieldEvidenceBundle,
    GraphInput,
    NormalizedBlock,
    TaskSpec,
)


def test_build_broad_extraction_messages_includes_task_and_blocks_summary():
    graph_input = GraphInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                text="发票号码：INV-001",
                page_no=1,
                meta_info={"block_id": "b-1"},
            )
        ],
        markdown="发票号码：INV-001",
        md_list=["发票号码：INV-001"],
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
    assert payload["task_name"] == "invoice"
    assert payload["metadata"] == {"source": "backend"}
    assert payload["blocks"][0]["document_id"] == "doc-1"
    assert payload["blocks"][0]["text"] == "发票号码：INV-001"
    assert payload["fields"][0]["field_name"] == "invoice_no"


def test_build_field_resolution_messages_focuses_on_target_field_and_evidence_bundle():
    graph_input = GraphInput(
        blocks=[NormalizedBlock(document_id="doc-2", text="金额：100.00")],
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
            FieldEvidenceBundle(
                field_name="amount",
                relevant_block_ids=["b-amount"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
            FieldEvidenceBundle(
                field_name="invoice_no",
                relevant_block_ids=["b-invoice"],
                evidence_texts=["发票号：INV-002"],
                local_status="evidence_found",
            ),
        ]
    )

    messages = prompts.build_field_resolution_messages(
        graph_input=graph_input,
        target_field_name="amount",
        broad_output=broad_output,
    )

    assert messages[0]["role"] == "system"
    assert "result + trace" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["target_field_name"] == "amount"
    assert payload["target_field"]["field_name"] == "amount"
    assert payload["target_field"]["relevant_block_ids"] == ["b-amount"]
    assert [field["field_name"] for field in payload["all_field_outputs"]] == [
        "amount",
        "invoice_no",
    ]
    assert payload["blocks"][0]["document_id"] == "doc-2"
