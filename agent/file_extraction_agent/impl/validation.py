"""字段定案后的 validation_rules 和基础字段约束后处理。"""

from __future__ import annotations

import re
from typing import Any

from file_extraction_agent.impl.block_ids import require_block_id
from file_extraction_agent.impl.schemas import FieldDecision, FieldEvidence
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import FieldDefinition, FieldEvidenceRef, NormalizedBlock, TraceAction


def apply_validation_rules(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
    state: GraphState,
    prior_decisions: list[FieldDecision],
) -> FieldDecision:
    """按 task spec 中的通用 validation_rules 校正字段定案结果。"""

    rules = field.validation_rules
    if not rules:
        return decision

    if rules.get("source_type") == "table_rows":
        return _apply_table_row_rules(decision=decision, field=field, state=state)

    if rules.get("operation") == "count_items":
        return _apply_count_items_rule(decision=decision, field=field, prior_decisions=prior_decisions)

    return decision


def apply_field_constraints(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
) -> FieldDecision:
    """按 FieldDefinition 的基础约束检查模型最终字段值。"""

    if decision.status != "resolved":
        return decision

    violation = _field_constraint_violation(decision=decision, field=field)
    if violation is None:
        return decision

    constraint, message = violation
    return FieldDecision(
        field_name=decision.field_name,
        status="failed",
        evidence=decision.evidence,
        related_fields=list(decision.related_fields),
        field_reference_records=list(decision.field_reference_records),
        lookup_records=list(decision.lookup_records),
        trace_actions=[
            *list(decision.trace_actions),
            TraceAction(
                action_type="field_constraint",
                message=message,
                refs=list(decision.evidence.evidence_refs),
                metadata={
                    "constraint": constraint,
                    "field_type": field.type,
                    "value": decision.value,
                },
            ),
        ],
        failure_reason=message,
    )


def _apply_table_row_rules(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
    state: GraphState,
) -> FieldDecision:
    matched_rows = _select_table_rows(
        blocks=state.extraction_input.blocks,
        rules=field.validation_rules,
    )
    target_column = field.validation_rules.get("target_column")
    if not target_column or not matched_rows:
        return decision

    output_rules = field.validation_rules.get("output", {})
    rows_with_values = [
        (row, value)
        for row in matched_rows
        if (value := row["values"].get(target_column, ""))
    ]
    if not rows_with_values:
        return decision

    matched_rows = [row for row, _ in rows_with_values]
    values = [value for _, value in rows_with_values]
    if output_rules.get("deduplicate"):
        values = _deduplicate_preserving_order(values)

    separator = output_rules.get("separator", "、")
    evidence = FieldEvidence(
        field_name=field.field_name,
        relevant_block_ids=_deduplicate_preserving_order(
            [row["block_id"] for row in matched_rows]
        ),
        evidence_texts=[row["text"] for row in matched_rows],
        evidence_refs=[row["ref"] for row in matched_rows],
        local_status="validated_by_rules",
        local_notes=["按 validation_rules.table_rows 从标准化 blocks 重新筛选证据"],
    )
    return FieldDecision(
        field_name=field.field_name,
        status="resolved",
        value=separator.join(values),
        evidence=evidence,
        related_fields=list(decision.related_fields),
        field_reference_records=list(decision.field_reference_records),
        lookup_records=list(decision.lookup_records),
        trace_actions=[
            *list(decision.trace_actions),
            TraceAction(
                action_type="validation_rule",
                message="按 validation_rules.table_rows 从标准化 blocks 重新筛选证据",
                refs=[row["ref"] for row in matched_rows],
                used_in_final_decision=True,
                metadata={
                    "rule_type": "table_rows",
                    "matched_block_ids": _deduplicate_preserving_order(
                        [row["block_id"] for row in matched_rows]
                    ),
                    "target_column": target_column,
                },
            ),
        ],
        reason="按字段 validation_rules 从表格行筛选并覆盖模型定案结果",
    )


def _apply_count_items_rule(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
    prior_decisions: list[FieldDecision],
) -> FieldDecision:
    source_field = field.validation_rules.get("source_field")
    if not source_field:
        return decision

    source_decision = next(
        (item for item in prior_decisions if item.field_name == source_field),
        None,
    )
    if source_decision is None or source_decision.status != "resolved":
        return decision

    separator = field.validation_rules.get("separator")
    values = _split_items(source_decision.value, separator=separator)
    return FieldDecision(
        field_name=field.field_name,
        status="resolved",
        value=str(len(values)),
        evidence=source_decision.evidence,
        related_fields=_deduplicate_preserving_order(
            [*decision.related_fields, source_field]
        ),
        field_reference_records=list(decision.field_reference_records),
        lookup_records=list(decision.lookup_records),
        trace_actions=[
            *list(decision.trace_actions),
            TraceAction(
                action_type="validation_rule",
                message=f"按 validation_rules 从字段 {source_field} 的条目数计算得到",
                refs=list(source_decision.evidence.evidence_refs),
                used_in_final_decision=True,
                metadata={
                    "rule_type": "count_items",
                    "source_field": source_field,
                },
            ),
        ],
        reason=f"按 validation_rules 从字段 {source_field} 的条目数计算得到",
    )


def _select_table_rows(
    *,
    blocks: list[NormalizedBlock],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    columns = rules.get("columns") or []
    matched_rows: list[dict[str, Any]] = []
    for block in blocks:
        for row in _extract_table_rows(block.text, columns=columns):
            values = row["values"]
            if not _matches_condition(values, rules.get("filter")):
                continue
            if any(_matches_condition(values, condition) for condition in rules.get("exclude", [])):
                continue
            matched_rows.append(
                {
                    "values": values,
                    "text": row["text"],
                    "block_id": require_block_id(block),
                    "ref": FieldEvidenceRef(
                        document_id=block.document_id,
                        page=block.page_no,
                        block_id=require_block_id(block),
                        span=row["text"],
                    ),
                }
            )
    return matched_rows


def _extract_table_rows(text: str, *, columns: list[str]) -> list[dict[str, Any]]:
    column_count = len(columns)
    if column_count == 0:
        return []

    row_pattern = "\\|" + "".join(r"\s*([^|]*)\s*\|" for _ in range(column_count))
    rows: list[dict[str, Any]] = []
    for match in re.findall(row_pattern, text):
        row_cells = [cell.strip() for cell in match]
        if _is_separator_row(row_cells) or row_cells == columns:
            continue
        values = dict(zip(columns, row_cells))
        rows.append(
            {
                "values": values,
                "text": "| " + " | ".join(row_cells) + " |",
            }
        )
    return rows


def _matches_condition(values: dict[str, str], condition: Any) -> bool:
    if not condition:
        return True
    column = condition.get("column")
    if not column:
        return False
    current = values.get(column, "")
    if "equals" in condition:
        return current == condition["equals"]
    if "contains" in condition:
        return str(condition["contains"]) in current
    return False


def _split_items(value: Any, *, separator: str | None = None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    if separator:
        parts = text.split(separator)
    else:
        parts = text.replace("，", ",").replace("、", ",").split(",")
    return [part.strip() for part in parts if part.strip()]


def _is_separator_row(cells: list[str]) -> bool:
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return deduplicated


def _field_constraint_violation(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
) -> tuple[str, str] | None:
    value = decision.value
    if field.required and not field.allow_missing and _is_missing_value(value):
        return "required", f"字段 {field.field_name} 是必填项，但模型返回空值"

    if field.type == "enum" and field.enum_values:
        if not isinstance(value, str) or value not in field.enum_values:
            return (
                "enum_values",
                f"字段 {field.field_name} 的值不在 enum_values 范围内: {value}",
            )

    if field.type == "money":
        if isinstance(value, bool) or not _looks_like_money(value):
            return "money", f"字段 {field.field_name} 的金额值格式无效: {value}"

    if field.type == "date":
        if not isinstance(value, str) or not _looks_like_date(value):
            return "date", f"字段 {field.field_name} 的日期值格式无效: {value}"

    if field.type == "boolean" and not isinstance(value, bool):
        return "boolean", f"字段 {field.field_name} 的布尔值格式无效: {value}"

    return None


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _looks_like_money(value: Any) -> bool:
    if isinstance(value, int | float):
        return True
    if not isinstance(value, str):
        return False
    return bool(re.search(r"\d", value))


def _looks_like_date(value: str) -> bool:
    patterns = [
        r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日?",
    ]
    return any(re.search(pattern, value) for pattern in patterns)
