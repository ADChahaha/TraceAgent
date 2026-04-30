from __future__ import annotations

import json

from service.file_extraction_agent.impl.broad import prompts as broad_prompts
from service.file_extraction_agent.impl.resolution import prompts as resolution_prompts
from service.file_extraction_agent.impl.schemas import ExtractionInput
from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.impl.tools.candidates import add_broad_candidate
from service.file_extraction_agent.schemas import (
    FieldDefinition,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


def test_build_broad_messages_focuses_on_field_and_search_contract():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-1",
                text="发票号码：INV-001",
                page_no=1,
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
                    lookup_hints=["发票号码"],
                )
            ],
        ),
        metadata={"source": "backend"},
    )
    state = build_graph_state(extraction_input)

    messages = broad_prompts.build_broad_messages(
        state=state,
        field=extraction_input.task_spec.fields[0],
        tool_results=[],
    )

    assert messages[0]["role"] == "system"
    assert "BroadAction" in messages[0]["content"]
    assert "search_grep" in messages[0]["content"]
    assert "query 格式固定为" in messages[0]["content"]
    assert " OR " in messages[0]["content"]
    assert "finish_broad" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["task_name"] == "invoice"
    assert payload["field"]["field_name"] == "invoice_no"
    assert payload["metadata"] == {"source": "backend"}
    assert payload["searchable_summary"]["paragraph_count"] == 1
    assert payload["current_candidates"] == []
    assert payload["tool_contract"]["search_grep"]["query_format"] == "term1 OR term2 OR term3"
    assert "同时搜索正文段落和表格行" in payload["tool_contract"]["search_grep"]["description"]
    assert payload["tool_contract"]["finish_broad"]["description"] == "当前字段 broad 阶段的唯一正常出口。"


def test_build_resolution_messages_includes_candidate_pool_and_prior_decisions():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-2", block_id="b-amount", text="金额：100.00"),
            NormalizedBlock(document_id="doc-2", block_id="b-invoice", text="发票号：INV-002"),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(field_name="amount", display_name="金额", type="money"),
                FieldDefinition(field_name="invoice_no", display_name="发票号", type="string"),
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    add_broad_candidate(
        state=state,
        field_name="amount",
        refs=["b-amount:p:p1"],
        reason="broad 找到金额候选",
    )

    messages = resolution_prompts.build_resolution_messages(
        state=state,
        field=extraction_input.task_spec.fields[0],
        tool_results=[],
    )

    assert messages[0]["role"] == "system"
    assert "FieldResolutionAction" in messages[0]["content"]
    assert "search_grep" in messages[0]["content"]
    assert "query 格式固定为" in messages[0]["content"]
    assert "final_decision" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["target_field"]["field_name"] == "amount"
    assert payload["candidate_bundle"][0]["candidate_id"] == "c1"
    assert payload["candidate_bundle"][0]["text"] == "金额：100.00"
    assert payload["completed_fields"] == []
    assert "blocks" not in payload
    assert payload["tool_contract"]["search_grep"]["query_format"] == "term1 OR term2 OR term3"
    assert payload["tool_contract"]["final_decision"]["description"] == "当前字段 resolution 阶段的唯一正常出口。"


def test_prompt_builders_apply_prompt_budget_limits():
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-1", text="A" * 20),
            NormalizedBlock(document_id="doc-1", block_id="b-2", text="B" * 20),
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[FieldDefinition(field_name="amount", display_name="金额", type="money")],
        ),
        options=RunOptions(
            max_prompt_blocks=1,
            max_prompt_block_chars=5,
            max_resolution_candidates=1,
        ),
    )
    state = build_graph_state(extraction_input)
    add_broad_candidate(state=state, field_name="amount", refs=["b-1:p:p1"], reason="A")
    add_broad_candidate(state=state, field_name="amount", refs=["b-2:p:p1"], reason="B")

    broad_messages = broad_prompts.build_broad_messages(
        state=state,
        field=extraction_input.task_spec.fields[0],
        tool_results=[],
    )
    broad_payload = json.loads(broad_messages[1]["content"])

    assert broad_payload["sample_paragraphs"][0]["text"] == "AAAAA"
    assert broad_payload["prompt_budget"]["omitted_paragraph_count"] == 1

    resolution_messages = resolution_prompts.build_resolution_messages(
        state=state,
        field=extraction_input.task_spec.fields[0],
        tool_results=[],
    )
    resolution_payload = json.loads(resolution_messages[1]["content"])

    assert [item["candidate_id"] for item in resolution_payload["candidate_bundle"]] == ["c1"]
    assert resolution_payload["prompt_budget"]["omitted_candidate_count"] == 1
