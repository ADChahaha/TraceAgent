from __future__ import annotations

import json

import pytest

from service.file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    ExtractionInput,
    FieldEvidence,
    FieldResolutionDecision,
)
from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.schemas import (
    FieldDefinition,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


def _build_extraction_input() -> ExtractionInput:
    return ExtractionInput(
        blocks=[
            NormalizedBlock(document_id="doc-1", block_id="b-invoice", text="发票号：INV-001"),
            NormalizedBlock(document_id="doc-1", block_id="b-amount", text="金额：100.00"),
        ],
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
    from service.file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_extraction_input())

    with pytest.raises(ValueError, match="evidence_collection"):
        run_resolution(state=state, extractor_client=object())


def test_run_resolution_requires_model_client_and_does_not_use_local_fallback():
    from service.file_extraction_agent.impl.resolution import run_resolution

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
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

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
                decision=FieldResolutionDecision(
                    status="resolved",
                    value=value,
                    used_block_ids=["b-invoice" if field_name == "invoice_no" else "b-amount"],
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
    assert state.field_decisions[0].evidence.relevant_block_ids == ["b-invoice"]
    assert state.field_decisions[0].evidence.evidence_texts == ["发票号：INV-001"]


def test_run_resolution_rejects_unknown_used_block_ids_from_model_decision():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="100.00",
                    used_block_ids=["b-missing"],
                    reason="模型引用了不存在的 block",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-amount", text="金额：100.00")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[FieldDefinition(field_name="amount", display_name="金额", type="money")],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-amount"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            )
        ]
    )

    with pytest.raises(ValueError, match="unknown used_block_ids: b-missing"):
        run_resolution(state=state, extractor_client=FakeExtractorClient())


def test_run_resolution_downgrades_invalid_enum_value_to_failed_decision():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="approval_status",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="pending",
                    used_block_ids=["b-status"],
                    reason="模型返回了 schema 外状态",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-status", text="状态：pending")],
        task_spec=TaskSpec(
            task_name="approval",
            fields=[
                FieldDefinition(
                    field_name="approval_status",
                    display_name="审批状态",
                    type="enum",
                    enum_values=["approved", "rejected"],
                    required=True,
                )
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="approval_status",
                relevant_block_ids=["b-status"],
                evidence_texts=["状态：pending"],
                local_status="evidence_found",
            )
        ]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())

    decision = state.field_decisions[0]
    assert decision.status == "failed"
    assert decision.value is None
    assert "enum_values" in decision.failure_reason
    action = decision.to_field_trace().actions[0]
    assert action.action_type == "field_constraint"
    assert action.metadata["constraint"] == "enum_values"


def test_run_resolution_only_uses_lookup_when_model_requests_it():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

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
            assert tool_records[0]["action_type"] == "global_lookup"
            assert tool_records[0]["metadata"]["returned_block_ids"] == [
                "b-lookup-1",
                "b-lookup-2",
            ]
            assert tool_records[0]["metadata"]["returned_to_model"] is True
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="888.00",
                    used_block_ids=["b-lookup-1"],
                    reason="模型基于 lookup 补充证据完成定案",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-lookup-1",
                text="应付金额：888.00 元",
                page_no=3,
            ),
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-lookup-2",
                text="合计应付金额：888.00 元",
                page_no=3,
            ),
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
        options=RunOptions(max_lookup_calls_per_field=1, lookup_top_k=2),
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
    assert decision.evidence.relevant_block_ids == ["b-lookup-1"]
    assert decision.evidence.evidence_texts == ["应付金额：888.00 元"]
    assert decision.lookup_records[0].target_field_name == "amount"
    assert decision.lookup_records[0].returned_block_ids == ["b-lookup-1", "b-lookup-2"]
    assert decision.lookup_records[0].returned_to_model is True
    assert decision.lookup_records[0].used_in_final_decision is True


def test_run_resolution_recomputes_lookup_usage_after_validation_override():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

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
                    target_field_name="selected_rooms",
                    query_reason="需要补查 selected_rooms",
                    lookup_hints=["selected_rooms"],
                )
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="selected_rooms",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="错误房间",
                    used_block_ids=["b-lookup"],
                    reason="模型先使用 lookup 结果定案",
                ),
            )

    field = FieldDefinition(
        field_name="selected_rooms",
        display_name="选中房间",
        type="string",
        validation_rules={
            "source_type": "table_rows",
            "columns": ["building", "room", "status"],
            "target_column": "room",
            "filter": {"column": "status", "equals": "selected"},
        },
        lookup_hints=["selected_rooms"],
    )
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-lookup",
                text="selected_rooms 错误房间",
            ),
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                kind="table",
                text=(
                    "| building | room | status | "
                    "|---|---|---| "
                    "| B1 | A101 | selected |"
                ),
            ),
        ],
        task_spec=TaskSpec(task_name="room-selection", fields=[field]),
        options=RunOptions(max_lookup_calls_per_field=1, lookup_top_k=1),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="selected_rooms", local_status="missing")]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())

    decision = state.field_decisions[0]
    assert decision.value == "A101"
    assert decision.evidence.relevant_block_ids == ["b-table"]
    assert decision.lookup_records[0].returned_block_ids == ["b-lookup"]
    assert decision.lookup_records[0].used_in_final_decision is False


def test_run_resolution_enforces_lookup_call_limit():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return FieldResolutionAction(
                action="lookup_blocks",
                target_field_name="amount",
                query_reason="持续请求 lookup",
                lookup_hints=["应付金额"],
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
        options=RunOptions(max_lookup_calls_per_field=1, lookup_top_k=1),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="amount", local_status="missing")]
    )

    with pytest.raises(ValueError, match="lookup_blocks action exceeded limit"):
        run_resolution(state=state, extractor_client=FakeExtractorClient())


def test_run_resolution_records_field_reference_action_when_model_requests_bundle():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def __init__(self):
            self.payloads = []

        def invoke(self, *, output_schema, messages):
            del output_schema
            payload = json.loads(messages[1]["content"])
            self.payloads.append(payload)
            if payload["target_field_name"] == "invoice_no":
                return FieldResolutionAction(
                    action="final_decision",
                    target_field_name="invoice_no",
                    decision=FieldResolutionDecision(
                        status="resolved",
                        value="INV-001",
                        used_block_ids=["b-invoice"],
                        reason="发票号证据充分",
                    ),
                )
            amount_payloads = [
                item for item in self.payloads if item["target_field_name"] == "amount"
            ]
            if len(amount_payloads) == 1:
                return FieldResolutionAction(
                    action="get_field_bundle",
                    target_field_name="amount",
                    requested_field_name="invoice_no",
                )
            tool_records = payload["tool_records"]
            assert tool_records[0]["action_type"] == "field_reference"
            assert tool_records[0]["metadata"]["requested_field_name"] == "invoice_no"
            assert tool_records[0]["metadata"]["found"] is True
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="100.00",
                    used_block_ids=["b-amount"],
                    related_fields=["invoice_no"],
                    reason="参考发票号字段后完成金额定案",
                ),
            )

    extraction_input = _build_extraction_input()
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-invoice"],
                evidence_texts=["发票号：INV-001"],
                local_status="evidence_found",
            ),
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-amount"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
        ]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())

    amount_decision = state.field_decisions[1]
    actions = amount_decision.to_field_trace().actions
    assert actions[0].action_type == "field_reference"
    assert actions[0].metadata["requested_field_name"] == "invoice_no"
    assert amount_decision.related_fields == ["invoice_no"]


def test_run_resolution_records_missing_field_reference_as_returned_tool_record():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def __init__(self):
            self.payloads = []

        def invoke(self, *, output_schema, messages):
            del output_schema
            payload = json.loads(messages[1]["content"])
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                return FieldResolutionAction(
                    action="get_field_bundle",
                    target_field_name="amount",
                    requested_field_name="missing_field",
                )
            tool_records = payload["tool_records"]
            assert tool_records[0]["action_type"] == "field_reference"
            assert tool_records[0]["metadata"]["requested_field_name"] == "missing_field"
            assert tool_records[0]["metadata"]["found"] is False
            assert tool_records[0]["metadata"]["returned_to_model"] is True
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldResolutionDecision(
                    status="failed",
                    used_block_ids=[],
                    failure_reason="参考字段不存在，金额无法可靠定案",
                ),
            )

    extraction_input = ExtractionInput(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="金额缺失")],
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="amount",
                    display_name="金额",
                    type="money",
                )
            ],
        ),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="amount", local_status="missing")]
    )

    run_resolution(state=state, extractor_client=FakeExtractorClient())

    action = state.field_decisions[0].to_field_trace().actions[0]
    assert action.action_type == "field_reference"
    assert action.metadata["found"] is False
    assert action.metadata["returned_to_model"] is True


def test_run_resolution_does_not_lookup_missing_evidence_without_model_request():
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema, messages
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="amount",
                decision=FieldResolutionDecision(
                    status="failed",
                    used_block_ids=[],
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
    from service.file_extraction_agent.impl.resolution import run_resolution
    from service.file_extraction_agent.impl.schemas import FieldResolutionAction

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema
            payload = json.loads(messages[1]["content"])
            field_name = payload["target_field_name"]
            if field_name == "selected_rooms":
                return FieldResolutionAction(
                    action="final_decision",
                    target_field_name="selected_rooms",
                    decision=FieldResolutionDecision(
                        status="resolved",
                        value="A101, A102, A103",
                        used_block_ids=["b-table"],
                        reason="模型把所有标记行都算进来了",
                    ),
                )
            return FieldResolutionAction(
                action="final_decision",
                target_field_name="selected_room_count",
                decision=FieldResolutionDecision(
                    status="resolved",
                    value="3",
                    used_block_ids=["b-table"],
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
    trace_actions = decisions_by_name["selected_rooms"].to_field_trace().actions
    assert trace_actions[0].action_type == "validation_rule"
    assert trace_actions[0].metadata["rule_type"] == "table_rows"
    assert trace_actions[0].metadata["matched_block_ids"] == ["b-table"]
    count_actions = decisions_by_name["selected_room_count"].to_field_trace().actions
    assert count_actions[0].action_type == "validation_rule"
    assert count_actions[0].metadata["rule_type"] == "count_items"
    assert count_actions[0].metadata["source_field"] == "selected_rooms"
