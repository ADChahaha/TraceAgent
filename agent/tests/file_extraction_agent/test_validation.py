from __future__ import annotations

from service.file_extraction_agent.impl.schemas import ExtractionInput, FieldDecision, FieldEvidence
from service.file_extraction_agent.impl.state import build_graph_state
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


def test_apply_validation_rules_corrects_table_rows_in_dedicated_module():
    from service.file_extraction_agent.impl.validation import apply_validation_rules

    field = FieldDefinition(
        field_name="selected_rooms",
        display_name="选中房间",
        type="string",
        validation_rules={
            "source_type": "table_rows",
            "columns": ["building", "room", "status"],
            "target_column": "room",
            "filter": {"column": "status", "equals": "selected"},
            "exclude": [{"column": "status", "equals": "rejected"}],
            "output": {"separator": ", ", "deduplicate": True},
        },
    )
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                kind="table",
                text=(
                    "| building | room | status | "
                    "|---|---|---| "
                    "| B1 | A101 | selected | "
                    "| B1 | A102 | rejected |"
                ),
            )
        ],
        task_spec=TaskSpec(task_name="room-selection", fields=[field]),
    )
    state = build_graph_state(extraction_input)
    decision = FieldDecision(
        field_name="selected_rooms",
        status="resolved",
        value="A101, A102",
        evidence=FieldEvidence(
            field_name="selected_rooms",
            relevant_block_ids=["b-table"],
            evidence_texts=[extraction_input.blocks[0].text],
            local_status="model_resolved",
        ),
        reason="模型初始定案",
    )

    corrected = apply_validation_rules(
        decision=decision,
        field=field,
        state=state,
        prior_decisions=[],
    )

    assert corrected.value == "A101"
    assert corrected.evidence.evidence_texts == ["| B1 | A101 | selected |"]
    assert corrected.trace_actions[0].action_type == "validation_rule"


def test_apply_validation_rules_keeps_model_decision_when_target_column_is_empty():
    from service.file_extraction_agent.impl.validation import apply_validation_rules

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
    )
    extraction_input = ExtractionInput(
        blocks=[
            NormalizedBlock(
                document_id="doc-1",
                block_id="b-table",
                kind="table",
                text=(
                    "| building | room | status | "
                    "|---|---|---| "
                    "| B1 |  | selected |"
                ),
            )
        ],
        task_spec=TaskSpec(task_name="room-selection", fields=[field]),
    )
    state = build_graph_state(extraction_input)
    decision = FieldDecision(
        field_name="selected_rooms",
        status="resolved",
        value="A101",
        evidence=FieldEvidence(
            field_name="selected_rooms",
            relevant_block_ids=["b-table"],
            evidence_texts=["模型原始证据"],
            local_status="model_resolved",
        ),
        reason="模型初始定案",
    )

    corrected = apply_validation_rules(
        decision=decision,
        field=field,
        state=state,
        prior_decisions=[],
    )

    assert corrected.value == "A101"
    assert corrected.evidence.evidence_texts == ["模型原始证据"]
    assert corrected.trace_actions == []


def test_apply_field_constraints_downgrades_invalid_enum_in_dedicated_module():
    from service.file_extraction_agent.impl.validation import apply_field_constraints

    field = FieldDefinition(
        field_name="approval_status",
        display_name="审批状态",
        type="enum",
        enum_values=["approved", "rejected"],
        required=True,
    )
    decision = FieldDecision(
        field_name="approval_status",
        status="resolved",
        value="pending",
        evidence=FieldEvidence(
            field_name="approval_status",
            relevant_block_ids=["b-status"],
            evidence_texts=["状态：pending"],
            local_status="model_resolved",
        ),
        reason="模型返回了 schema 外状态",
    )

    constrained = apply_field_constraints(decision=decision, field=field)

    assert constrained.status == "failed"
    assert constrained.value is None
    assert "enum_values" in constrained.failure_reason
    assert constrained.trace_actions[0].action_type == "field_constraint"
