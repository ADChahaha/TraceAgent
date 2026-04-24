from __future__ import annotations

import json

import pytest

from file_extraction_agent.impl.schemas import EvidenceCollection, ExtractionInput, FieldEvidence
from file_extraction_agent.impl.state import build_graph_state
from file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def _build_extraction_input() -> ExtractionInput:
    return ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", text="测试文档")],
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


def test_run_resolution_requires_evidence_collection_before_model_resolution():
    from file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_extraction_input())

    with pytest.raises(ValueError, match="evidence_collection"):
        run_resolution(state=state, extractor_client=object())


def test_run_resolution_requires_model_client_and_does_not_use_local_fallback():
    from file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_extraction_input())
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-1"],
                evidence_texts=["发票号：INV-001"],
                local_status="evidence_found",
            )
        ]
    )

    with pytest.raises(ValueError, match="extractor_client"):
        run_resolution(state=state)

    assert state.field_decisions == []


def test_run_resolution_invokes_model_action_for_each_field_decision():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision, FieldResolutionAction

    class FakeExtractorClient:
        def __init__(self):
            self.calls = []

        def invoke(self, *, output_schema, messages):
            self.calls.append((output_schema, messages))
            payload = json.loads(messages[1]["content"])
            if payload["target_field_name"] == "invoice_no":
                field_name = "invoice_no"
                value = "INV-MODEL"
            else:
                field_name = "amount"
                value = "100.00"
            return FieldResolutionAction(
                action="final_decision",
                target_field_name=field_name,
                decision=FieldDecision(
                    field_name=field_name,
                    status="resolved",
                    value=value,
                    evidence=FieldEvidence(
                        field_name=field_name,
                        evidence_texts=[value],
                        local_status="model_resolved",
                    ),
                    related_fields=[field_name],
                    reason="模型完成字段定案",
                ),
            )

    state = build_graph_state(_build_extraction_input())
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                evidence_texts=["发票号：INV-MODEL"],
                local_status="evidence_found",
            ),
            FieldEvidence(
                field_name="amount",
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
        ]
    )
    fake_client = FakeExtractorClient()

    returned_state = run_resolution(state=state, extractor_client=fake_client)

    assert returned_state is state
    assert [call[0] for call in fake_client.calls] == [
        FieldResolutionAction,
        FieldResolutionAction,
    ]
    assert [field.value for field in state.field_decisions] == ["INV-MODEL", "100.00"]


def test_run_resolution_only_uses_lookup_when_model_requests_it():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision, FieldResolutionAction

    class FakeExtractorClient:
        def __init__(self):
            self.payloads = []

        def invoke(self, *, output_schema, messages):
            assert output_schema is FieldResolutionAction
            payload = json.loads(messages[1]["content"])
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                return FieldResolutionAction(
                    action="lookup_blocks",
                    target_field_name="amount",
                    query_reason="broad 阶段没有给出金额所在 block，需要从全量 blocks 补查",
                    lookup_hints=["应付金额"],
                )
            tool_records = payload["tool_records"]
            assert tool_records[0]["returned_block_ids"] == ["b-lookup"]
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldDecision(
                    field_name="amount",
                    status="resolved",
                    value="888.00",
                    evidence=FieldEvidence(
                        field_name="amount",
                        relevant_block_ids=["b-lookup"],
                        evidence_texts=["应付金额：888.00 元"],
                        local_status="model_resolved_with_lookup",
                    ),
                    reason="模型基于 lookup 补充证据完成定案",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-lookup",
                text="应付金额：888.00 元",
                page_no=3,
            )
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                    lookup_hints=["应付金额"],
                )
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="amount", local_status="missing")]
    )
    fake_client = FakeExtractorClient()

    run_resolution(state=state, extractor_client=fake_client)

    decision = state.field_decisions[0]
    assert len(fake_client.payloads) == 2
    assert decision.status == "resolved"
    assert decision.lookup_records[0].target_field_name == "amount"
    assert decision.lookup_records[0].returned_block_ids == ["b-lookup"]
    assert decision.lookup_records[0].used_in_final_decision is True


def test_run_resolution_does_not_lookup_missing_evidence_without_model_request():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision, FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldDecision(
                    field_name="amount",
                    status="failed",
                    evidence=FieldEvidence(field_name="amount", local_status="missing"),
                    failure_reason="模型判断 broad 证据不足，且本轮不请求工具",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-lookup",
                text="应付金额：888.00 元",
                page_no=3,
            )
        ],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                    lookup_hints=["应付金额"],
                )
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="amount", local_status="missing")]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())

    decision = state.field_decisions[0]
    assert decision.status == "failed"
    assert decision.lookup_records == []


def test_run_resolution_applies_generic_table_row_rules_after_model_decision():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision, FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema
            payload = json.loads(messages[1]["content"])
            field_name = payload["target_field_name"]
            if field_name == "selected_rooms":
                return FieldResolutionAction(
                    action="final_decision",
                    target_field_name="selected_rooms",
                    decision=FieldDecision(
                        field_name="selected_rooms",
                        status="resolved",
                        value="A101, A102, A103",
                        evidence=FieldEvidence(
                            field_name="selected_rooms",
                            evidence_texts=["模型错误混入 rejected 行"],
                            local_status="model_resolved",
                        ),
                        reason="模型把所有标记行都算进来了",
                    ),
                )
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="selected_room_count",
                decision=FieldDecision(
                    field_name="selected_room_count",
                    status="resolved",
                    value="3",
                    evidence=FieldEvidence(
                        field_name="selected_room_count",
                        evidence_texts=["模型错误计数"],
                        local_status="model_resolved",
                    ),
                    reason="模型按错误列表计数",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                page_no=1,
                kind="table",
                text=(
                    "| building | room | score | status | "
                    "|---|---|---|---| "
                    "| B1 | A101 | 91 | selected | "
                    "| B1 | A102 | 95 | rejected | "
                    "| B1 | A103 | 92 | selected |"
                ),
            )
        ],
        task_spec=TaskSpec(
            task_name="generic_table_selection",
            fields=[
                FieldDefinition(
                    field_name="selected_rooms",
                    display_name="选中房间",
                    type="string",
                    validation_rules={
                        "source_type": "table_rows",
                        "columns": ["building", "room", "score", "status"],
                        "target_column": "room",
                        "filter": {"column": "status", "equals": "selected"},
                        "exclude": [{"column": "status", "equals": "rejected"}],
                        "output": {
                            "separator": ", ",
                            "deduplicate": True,
                            "preserve_order": True,
                        },
                    },
                ),
                FieldDefinition(
                    field_name="selected_room_count",
                    display_name="选中房间数量",
                    type="string",
                    validation_rules={
                        "source_field": "selected_rooms",
                        "operation": "count_items",
                    },
                    cross_field_hints=["selected_rooms"],
                ),
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="selected_rooms",
                relevant_block_ids=["b-table"],
                evidence_texts=[extraction_input.blocks[0].text],
                local_status="found",
            ),
            FieldEvidence(
                field_name="selected_room_count",
                relevant_block_ids=["b-table"],
                evidence_texts=[extraction_input.blocks[0].text],
                local_status="found",
            ),
        ]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())
    decisions_by_name = {decision.field_name: decision for decision in state.field_decisions}

    assert decisions_by_name["selected_rooms"].value == "A101, A103"
    assert decisions_by_name["selected_room_count"].value == "2"
    assert decisions_by_name["selected_rooms"].evidence.relevant_block_ids == ["b-table"]
    assert decisions_by_name["selected_rooms"].evidence.evidence_texts == [
        "| B1 | A101 | 91 | selected |",
        "| B1 | A103 | 92 | selected |",
    ]
