from __future__ import annotations

import json

from file_extraction_agent.impl import prompts
from file_extraction_agent.impl.schemas import EvidenceCollection, ExtractionInput, FieldEvidence, RunOptions
from file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_build_broad_extraction_messages_includes_task_and_blocks_summary():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-1",
                text="发票号码：INV-001",
                page_no=1,
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

    messages = prompts.build_broad_extraction_messages(extraction_input)

    assert messages[0]["role"] == "system"
    assert "EvidenceCollection" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["task_name"] == "invoice"
    assert payload["metadata"] == {"source": "backend"}
    assert payload["blocks"][0]["document_id"] == "doc-1"
    assert payload["blocks"][0]["text"] == "发票号码：INV-001"
    assert payload["fields"][0]["field_name"] == "invoice_no"
    assert "validation_rules" in messages[0]["content"]


def test_build_field_resolution_messages_focuses_on_target_field_and_evidence():
    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-2", text="金额：100.00")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
            ],
        ),
    )
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-amount"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-invoice"],
                evidence_texts=["发票号：INV-002"],
                local_status="evidence_found",
            ),
        ]
    )

    messages = prompts.build_field_resolution_messages(
        extraction_input=extraction_input,
        target_field_name="amount",
        evidence_collection=evidence_collection,
    )

    assert messages[0]["role"] == "system"
    assert "field resolution" in messages[0]["content"]
    assert "FieldResolutionAction" in messages[0]["content"]
    assert "lookup_blocks" in messages[0]["content"]
    assert "validation_rules" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["target_field_name"] == "amount"
    assert payload["target_field"]["field_name"] == "amount"
    assert payload["target_field"]["relevant_block_ids"] == ["b-amount"]
    assert payload["tool_evidence"] == []
    assert payload["tool_records"] == []
    assert [field["field_name"] for field in payload["all_field_evidence"]] == [
        "amount",
        "invoice_no",
    ]
    assert "blocks" not in payload


def test_prompt_builders_apply_prompt_budget_limits():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-1", text="A" * 20),
            NormalizedBlock(document_id="doc-1", block_id="b-2", text="B" * 20),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
            ],
        ),
        options=RunOptions(
            max_prompt_blocks=1,
            max_prompt_block_chars=5,
            max_resolution_evidence_fields=1,
            max_prompt_evidence_text_chars=4,
        ),
    )

    broad_messages = prompts.build_broad_extraction_messages(extraction_input)
    broad_payload = json.loads(broad_messages[1]["content"])

    assert [block["block_id"] for block in broad_payload["blocks"]] == ["b-1"]
    assert broad_payload["blocks"][0]["text"] == "AAAAA"
    assert broad_payload["prompt_budget"]["omitted_block_count"] == 1

    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-1"],
                evidence_texts=["金额证据文本很长"],
                local_status="found",
            ),
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-2"],
                evidence_texts=["发票证据文本很长"],
                local_status="found",
            ),
        ]
    )
    resolution_messages = prompts.build_field_resolution_messages(
        extraction_input=extraction_input,
        target_field_name="amount",
        evidence_collection=evidence_collection,
    )
    resolution_payload = json.loads(resolution_messages[1]["content"])

    assert [item["field_name"] for item in resolution_payload["all_field_evidence"]] == ["amount"]
    assert resolution_payload["target_field"]["evidence_texts"] == ["金额证据"]
    assert resolution_payload["prompt_budget"]["omitted_field_evidence_count"] == 1
