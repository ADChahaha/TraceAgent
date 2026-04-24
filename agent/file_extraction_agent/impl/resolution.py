"""file_extraction_agent 的 field resolution 节点。"""

from __future__ import annotations

import re
from typing import Any

from file_extraction_agent.impl.prompts import build_field_resolution_messages
from file_extraction_agent.impl.schemas import (
    FieldDecision,
    FieldEvidence,
    FieldResolutionAction,
    LookupRecord,
)
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.impl.tools import get_field_bundle, lookup_blocks_for_field
from file_extraction_agent.schemas import FieldDefinition, FieldEvidenceRef, NormalizedBlock


def run_resolution(*, state: GraphState, extractor_client: Any | None = None) -> GraphState:
    """执行第二阶段字段定案，并把字段决策写回图状态。"""

    if state.evidence_collection is None:
        raise ValueError("resolution requires evidence_collection before resolving fields")
    if extractor_client is None:
        raise ValueError("resolution requires extractor_client for model-based field decisions")

    state.field_decisions = []
    for field in state.extraction_input.task_spec.fields:
        decision = _resolve_field_with_model(
            state=state,
            extractor_client=extractor_client,
            field=field,
            prior_decisions=state.field_decisions,
        )
        state.field_decisions.append(decision)
    return state


def _resolve_field_with_model(
    *,
    state: GraphState,
    extractor_client: Any,
    field: FieldDefinition,
    prior_decisions: list[FieldDecision],
) -> FieldDecision:
    tool_evidence: list[FieldEvidence] = []
    lookup_records: list[LookupRecord] = []
    max_iterations = state.extraction_input.options.max_extra_lookups_per_field + 2

    for _ in range(max_iterations):
        action = extractor_client.invoke(
            output_schema=FieldResolutionAction,
            messages=build_field_resolution_messages(
                extraction_input=state.extraction_input,
                target_field_name=field.field_name,
                evidence_collection=state.evidence_collection,
                tool_evidence=[item.model_dump() for item in tool_evidence],
                tool_records=[item.model_dump() for item in lookup_records],
            ),
        )
        if action.target_field_name != field.field_name:
            raise ValueError("resolution action target_field_name does not match current field")

        if action.action == "final_decision":
            decision = action.decision
            if decision is None:
                raise ValueError("final_decision action requires decision")
            decision.lookup_records = _merge_lookup_records(
                list(decision.lookup_records),
                lookup_records,
            )
            return _apply_validation_rules(
                decision=decision,
                field=field,
                state=state,
                prior_decisions=prior_decisions,
            )

        if action.action == "get_field_bundle":
            bundle = get_field_bundle(
                state.evidence_collection,
                action.requested_field_name or "",
            )
            if bundle is not None:
                tool_evidence.append(bundle)
            continue

        if action.action == "lookup_blocks":
            if not state.extraction_input.options.allow_extra_lookup:
                raise ValueError("lookup_blocks action is disabled by run options")
            lookup_result = lookup_blocks_for_field(
                blocks=state.extraction_input.blocks,
                target_field_name=field.field_name,
                query_reason=action.query_reason or "模型请求从全量 blocks 补查字段证据",
                lookup_hints=action.lookup_hints or field.lookup_hints,
                top_k=state.extraction_input.options.max_extra_lookups_per_field,
            )
            lookup_result.record.used_in_final_decision = True
            lookup_records.append(lookup_result.record)
            if lookup_result.matched_blocks:
                tool_evidence.append(
                    FieldEvidence(
                        field_name=field.field_name,
                        relevant_block_ids=list(lookup_result.record.returned_block_ids),
                        evidence_texts=[block.text for block in lookup_result.matched_blocks],
                        evidence_refs=list(lookup_result.record.returned_refs),
                        local_status="lookup_found",
                        local_notes=["模型请求 lookup_blocks 后补充的证据"],
                    )
                )
            continue

    raise ValueError("resolution model did not return final_decision after tool requests")


def _merge_lookup_records(
    current_records: list[LookupRecord],
    new_records: list[LookupRecord],
) -> list[LookupRecord]:
    merged = list(current_records)
    seen = {
        (
            record.target_field_name,
            record.lookup_reason,
            tuple(record.returned_block_ids),
        )
        for record in merged
    }
    for record in new_records:
        key = (
            record.target_field_name,
            record.lookup_reason,
            tuple(record.returned_block_ids),
        )
        if key in seen:
            continue
        merged.append(record)
        seen.add(key)
    return merged


def _apply_validation_rules(
    *,
    decision: FieldDecision,
    field: FieldDefinition,
    state: GraphState,
    prior_decisions: list[FieldDecision],
) -> FieldDecision:
    rules = field.validation_rules
    if not rules:
        return decision

    if rules.get("source_type") == "table_rows":
        return _apply_table_row_rules(decision=decision, field=field, state=state)

    if rules.get("operation") == "count_items":
        return _apply_count_items_rule(decision=decision, field=field, prior_decisions=prior_decisions)

    return decision


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
    values = [row["values"].get(target_column, "") for row in matched_rows]
    values = [value for value in values if value]
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
        lookup_records=list(decision.lookup_records),
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
        lookup_records=list(decision.lookup_records),
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
                    "block_id": _block_id(block),
                    "ref": FieldEvidenceRef(
                        document_id=block.document_id,
                        page=block.page_no,
                        block_id=_block_id(block),
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


def _block_id(block: NormalizedBlock) -> str:
    if block.block_id:
        return block.block_id
    meta_block_id = block.meta_info.get("block_id")
    if meta_block_id:
        return str(meta_block_id)
    return f"{block.document_id}:{block.page_no or 0}:{abs(hash(block.text))}"
