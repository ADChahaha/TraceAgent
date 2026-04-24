from __future__ import annotations

import json

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


def test_resolve_fields_uses_task_spec_order_and_fills_missing_outputs():
    from file_extraction_agent.impl.resolution import resolve_fields

    extraction_input = _build_extraction_input()
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-1"],
                evidence_texts=["发票号：INV-001"],
                local_status="evidence_found",
            )
        ]
    )

    field_decisions = resolve_fields(
        task_spec=extraction_input.task_spec,
        evidence_collection=evidence_collection,
    )

    assert [field.field_name for field in field_decisions] == ["invoice_no", "amount"]
    assert field_decisions[0].status == "resolved"
    assert field_decisions[0].value == "发票号：INV-001"
    assert field_decisions[1].status == "failed"
    assert field_decisions[0].evidence.relevant_block_ids == ["b-1"]
    assert field_decisions[1].failure_reason == "未找到可用证据"


def test_resolve_fields_keeps_evidence_separate_from_result_value():
    from file_extraction_agent.impl.resolution import resolve_fields

    extraction_input = _build_extraction_input()
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-2"],
                evidence_texts=["发票号：INV-002"],
                local_status="evidence_found",
                local_notes=["字段证据来自表格"],
            ),
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-3"],
                evidence_texts=["金额：100.00"],
                local_status="evidence_found",
            ),
        ]
    )

    field_decisions = resolve_fields(
        task_spec=extraction_input.task_spec,
        evidence_collection=evidence_collection,
    )

    assert field_decisions[0].value == "发票号：INV-002"
    assert field_decisions[0].evidence.local_notes == ["字段证据来自表格"]


def test_run_resolution_reads_evidence_collection_and_writes_decisions_to_state():
    from file_extraction_agent.impl.resolution import run_resolution

    state = build_graph_state(_build_extraction_input())
    state.evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="invoice_no",
                relevant_block_ids=["b-4"],
                evidence_texts=["发票号：INV-005"],
                local_status="evidence_found",
            ),
            FieldEvidence(
                field_name="amount",
                relevant_block_ids=["b-5"],
                evidence_texts=["金额：200.00"],
                local_status="evidence_found",
            ),
        ]
    )

    returned_state = run_resolution(state=state)

    assert returned_state is state
    assert [field.status for field in state.field_decisions] == ["resolved", "resolved"]
    assert [field.value for field in state.field_decisions] == [
        "发票号：INV-005",
        "金额：200.00",
    ]
    assert [field.evidence.relevant_block_ids for field in state.field_decisions] == [
        ["b-4"],
        ["b-5"],
    ]


def test_run_resolution_invokes_model_client_for_field_decisions():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision

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
            return FieldDecision(
                field_name=field_name,
                status="resolved",
                value=value,
                evidence=FieldEvidence(
                    field_name=field_name,
                    evidence_texts=[value],
                    local_status="evidence_found",
                ),
                related_fields=[field_name],
                reason="模型完成字段定案",
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
    assert [call[0] for call in fake_client.calls] == [FieldDecision, FieldDecision]
    assert [field.value for field in state.field_decisions] == ["INV-MODEL", "100.00"]


def test_run_resolution_records_lookup_when_evidence_is_missing():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import RunOptions

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
        options=RunOptions(allow_extra_lookup=True),
    )
    state = build_graph_state(extraction_input)
    state.evidence_collection = EvidenceCollection(
        fields=[FieldEvidence(field_name="amount", local_status="missing")]
    )

    run_resolution(state=state)

    decision = state.field_decisions[0]
    assert decision.status == "resolved"
    assert decision.lookup_records[0].target_field_name == "amount"
    assert decision.lookup_records[0].returned_block_ids == ["b-lookup"]
    assert decision.lookup_records[0].used_in_final_decision is True


def test_run_resolution_applies_generic_table_row_rules_after_model_decision():
    from file_extraction_agent.impl.resolution import run_resolution
    from file_extraction_agent.impl.schemas import FieldDecision

    class FakeExtractorClient:
        def invoke(self, *, output_schema, messages):
            del output_schema
            payload = json.loads(messages[1]["content"])
            field_name = payload["target_field_name"]
            if field_name == "selected_rooms":
                return FieldDecision(
                    field_name="selected_rooms",
                    status="resolved",
                    value="A101, A102, A103",
                    evidence=FieldEvidence(
                        field_name="selected_rooms",
                        evidence_texts=["模型错误混入 rejected 行"],
                        local_status="model_resolved",
                    ),
                    reason="模型把所有标记行都算进来了",
                )
            return FieldDecision(
                field_name="selected_room_count",
                status="resolved",
                value="3",
                evidence=FieldEvidence(
                    field_name="selected_room_count",
                    evidence_texts=["模型错误计数"],
                    local_status="model_resolved",
                ),
                reason="模型按错误列表计数",
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


def test_resolve_fields_normalizes_civilized_dormitory_table_evidence():
    from file_extraction_agent.impl.resolution import resolve_fields

    task_spec = TaskSpec(
        task_name="civilized_dormitory",
        fields=[
            FieldDefinition(field_name="building_name", display_name="楼栋", type="string"),
            FieldDefinition(
                field_name="civilized_dormitory_rooms",
                display_name="文明寝室房间号",
                type="string",
            ),
            FieldDefinition(
                field_name="civilized_dormitory_count",
                display_name="文明寝室数量",
                type="string",
            ),
        ],
    )
    civilized_rows = [
        "| 18栋 | 212 | 89.92 | 文明寝室 |",
        "| 18栋 | 214 | 92.42 | 文明寝室 |",
        "| 18栋 | 302 | 88.08 | 文明寝室 |",
    ]
    evidence_collection = EvidenceCollection(
        fields=[
            FieldEvidence(
                field_name="building_name",
                evidence_texts=["| 18栋 | 101 | 84.5 | |", *civilized_rows],
                local_status="found",
            ),
            FieldEvidence(
                field_name="civilized_dormitory_rooms",
                evidence_texts=civilized_rows,
                local_status="found",
            ),
            FieldEvidence(
                field_name="civilized_dormitory_count",
                evidence_texts=civilized_rows,
                local_status="found",
            ),
        ]
    )

    field_decisions = resolve_fields(
        task_spec=task_spec,
        evidence_collection=evidence_collection,
    )
    decisions_by_name = {decision.field_name: decision for decision in field_decisions}

    assert decisions_by_name["building_name"].value == "18栋"
    assert decisions_by_name["civilized_dormitory_rooms"].value == "212、214、302"
    assert decisions_by_name["civilized_dormitory_count"].value == "3"
