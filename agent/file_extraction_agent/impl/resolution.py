"""file_extraction_agent 的 field resolution 节点。"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from file_extraction_agent.impl.prompts import build_field_resolution_messages
from file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    FieldDecision,
    FieldEvidence,
)
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.impl.tools import lookup_blocks_for_field
from file_extraction_agent.schemas import FieldDefinition, FieldEvidenceRef, NormalizedBlock, TaskSpec


def run_resolution(*, state: GraphState, extractor_client: Any | None = None) -> GraphState:
    """执行第二阶段字段定案，并把字段决策写回图状态。"""

    if state.evidence_collection is None:
        raise ValueError("resolution requires evidence_collection before resolving fields")

    if extractor_client is not None:
        model_decisions = [
            _apply_validation_rules(
                decision=extractor_client.invoke(
                output_schema=FieldDecision,
                messages=build_field_resolution_messages(
                    extraction_input=state.extraction_input,
                    target_field_name=field.field_name,
                    evidence_collection=state.evidence_collection,
                ),
                ),
                field=field,
                state=state,
                prior_decisions=[],
            )
            for field in state.extraction_input.task_spec.fields
        ]
        state.field_decisions = []
        for field, decision in zip(state.extraction_input.task_spec.fields, model_decisions):
            state.field_decisions.append(
                _apply_validation_rules(
                    decision=decision,
                    field=field,
                    state=state,
                    prior_decisions=state.field_decisions,
                )
            )
        return state

    state.field_decisions = resolve_fields(
        task_spec=state.extraction_input.task_spec,
        evidence_collection=state.evidence_collection,
        state=state,
    )
    return state


def resolve_fields(
    *,
    task_spec: TaskSpec,
    evidence_collection: EvidenceCollection,
    state: GraphState | None = None,
) -> list[FieldDecision]:
    """按 task spec 顺序把字段证据收口成内部字段决策。"""

    evidence_by_field = {
        field_evidence.field_name: field_evidence
        for field_evidence in evidence_collection.fields
    }
    field_decisions: list[FieldDecision] = []

    for field in task_spec.fields:
        field_decisions.append(
            resolve_single_field(
                field_name=field.field_name,
                field_evidence=evidence_by_field.get(field.field_name),
                state=state,
                lookup_hints=field.lookup_hints,
            )
        )

    return field_decisions


def resolve_single_field(
    *,
    field_name: str,
    field_evidence: FieldEvidence | None,
    state: GraphState | None = None,
    lookup_hints: list[str] | None = None,
) -> FieldDecision:
    """把单字段 evidence 收口成字段决策。"""

    if field_evidence is None or not field_evidence.evidence_texts:
        if state is not None and state.extraction_input.options.allow_extra_lookup:
            lookup_result = lookup_blocks_for_field(
                blocks=state.extraction_input.blocks,
                target_field_name=field_name,
                query_reason="字段证据缺失，按 lookup hints 从全量 blocks 补查",
                lookup_hints=lookup_hints or [],
                top_k=state.extraction_input.options.max_extra_lookups_per_field,
            )
            if lookup_result.matched_blocks:
                lookup_result.record.used_in_final_decision = True
                lookup_evidence = FieldEvidence(
                    field_name=field_name,
                    relevant_block_ids=list(lookup_result.record.returned_block_ids),
                    evidence_texts=[block.text for block in lookup_result.matched_blocks],
                    evidence_refs=list(lookup_result.record.returned_refs),
                    local_status="lookup_found",
                    local_notes=["broad 阶段证据缺失，resolution 触发全局补查"],
                )
                return FieldDecision(
                    field_name=field_name,
                    status="resolved",
                    value=_resolve_value_from_evidence(
                        field_name=field_name,
                        evidence_texts=lookup_evidence.evidence_texts,
                    ),
                    evidence=lookup_evidence,
                    related_fields=[field_name],
                    lookup_records=[lookup_result.record],
                    reason="通过全局补查找到字段证据并完成最小规则定案",
                )
        return FieldDecision(
            field_name=field_name,
            status="failed",
            evidence=field_evidence or _missing_evidence(field_name),
            related_fields=[field_name] if field_evidence is not None else [],
            failure_reason="未找到可用证据",
        )

    value = _resolve_value_from_evidence(
        field_name=field_name,
        evidence_texts=field_evidence.evidence_texts,
    )
    return FieldDecision(
        field_name=field_name,
        status="resolved",
        value=value,
        evidence=field_evidence,
        related_fields=[field_name],
        reason="基于字段证据文本完成最小规则定案",
    )


def _missing_evidence(field_name: str) -> FieldEvidence:
    return FieldEvidence(
        field_name=field_name,
        local_status="missing",
    )


def _resolve_value_from_evidence(*, field_name: str, evidence_texts: list[str]) -> str:
    table_rows = [_parse_markdown_table_row(text) for text in evidence_texts]
    table_rows = [row for row in table_rows if row is not None]
    if table_rows:
        if field_name == "building_name":
            buildings = [row[0] for row in table_rows if row[0]]
            if buildings:
                return Counter(buildings).most_common(1)[0][0]
        if field_name == "civilized_dormitory_rooms":
            room_numbers = [
                row[1]
                for row in table_rows
                if len(row) >= 4 and row[3] == "文明寝室" and row[1]
            ]
            if room_numbers:
                return "、".join(room_numbers)
        if field_name == "civilized_dormitory_count":
            civilized_count = sum(
                1 for row in table_rows if len(row) >= 4 and row[3] == "文明寝室"
            )
            if civilized_count:
                return str(civilized_count)
    return evidence_texts[0]


def _parse_markdown_table_row(text: str) -> list[str] | None:
    stripped = text.strip()
    if "|" not in stripped:
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if len(cells) < 2:
        return None
    return cells


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
