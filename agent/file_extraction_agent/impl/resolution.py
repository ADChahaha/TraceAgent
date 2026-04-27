"""file_extraction_agent 的 field resolution 节点。"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.block_ids import require_block_id
from file_extraction_agent.impl.prompts import build_field_resolution_messages
from file_extraction_agent.impl.schemas import (
    FieldDecision,
    FieldEvidence,
    FieldReferenceRecord,
    FieldResolutionAction,
    FieldResolutionDecision,
    LookupRecord,
)
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.impl.tools import get_field_bundle, lookup_blocks_for_field
from file_extraction_agent.impl.validation import apply_field_constraints, apply_validation_rules
from file_extraction_agent.schemas import FieldDefinition, FieldEvidenceRef


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
    field_reference_records: list[FieldReferenceRecord] = []
    lookup_records: list[LookupRecord] = []
    lookup_calls = 0
    max_iterations = (
        state.extraction_input.options.max_lookup_calls_per_field
        + len(state.extraction_input.task_spec.fields)
        + 2
    )

    for _ in range(max_iterations):
        action = extractor_client.invoke(
            output_schema=FieldResolutionAction,
            messages=build_field_resolution_messages(
                extraction_input=state.extraction_input,
                target_field_name=field.field_name,
                evidence_collection=state.evidence_collection,
                tool_evidence=[item.model_dump() for item in tool_evidence],
                tool_records=[
                    *[
                        item.to_trace_action().model_dump()
                        for item in field_reference_records
                    ],
                    *[item.to_trace_action().model_dump() for item in lookup_records],
                ],
            ),
        )
        if action.target_field_name != field.field_name:
            raise ValueError("resolution action target_field_name does not match current field")

        if action.action == "final_decision":
            model_decision = action.decision
            if model_decision is None:
                raise ValueError("final_decision action requires decision")
            decision = _build_field_decision_from_model(
                model_decision=model_decision,
                field=field,
                state=state,
            )
            decision.field_reference_records = _merge_field_reference_records(
                list(decision.field_reference_records),
                field_reference_records,
                related_fields=decision.related_fields,
            )
            decision.lookup_records = _merge_lookup_records(
                list(decision.lookup_records),
                lookup_records,
                used_block_ids=decision.evidence.relevant_block_ids,
            )
            decision = apply_validation_rules(
                decision=decision,
                field=field,
                state=state,
                prior_decisions=prior_decisions,
            )
            decision = apply_field_constraints(decision=decision, field=field)
            return _refresh_tool_record_usage(decision)

        if action.action == "get_field_bundle":
            requested_field_name = action.requested_field_name or ""
            bundle = get_field_bundle(
                state.evidence_collection,
                requested_field_name,
            )
            field_reference_records.append(
                FieldReferenceRecord(
                    target_field_name=field.field_name,
                    requested_field_name=requested_field_name,
                    found=bundle is not None,
                    returned_refs=list(bundle.evidence_refs) if bundle is not None else [],
                    returned_to_model=True,
                )
            )
            if bundle is not None:
                tool_evidence.append(bundle)
            continue

        if action.action == "lookup_blocks":
            if not state.extraction_input.options.allow_extra_lookup:
                raise ValueError("lookup_blocks action is disabled by run options")
            if lookup_calls >= state.extraction_input.options.max_lookup_calls_per_field:
                raise ValueError("lookup_blocks action exceeded limit")
            lookup_calls += 1
            lookup_result = lookup_blocks_for_field(
                blocks=state.extraction_input.blocks,
                target_field_name=field.field_name,
                query_reason=action.query_reason or "模型请求从全量 blocks 补查字段证据",
                lookup_hints=action.lookup_hints or field.lookup_hints,
                top_k=state.extraction_input.options.lookup_top_k,
            )
            lookup_result.record.returned_to_model = True
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


def _build_field_decision_from_model(
    *,
    model_decision: FieldResolutionDecision,
    field: FieldDefinition,
    state: GraphState,
) -> FieldDecision:
    evidence = _evidence_from_used_block_ids(
        field_name=field.field_name,
        used_block_ids=model_decision.used_block_ids,
        state=state,
        status=model_decision.status,
    )
    return FieldDecision(
        field_name=field.field_name,
        status=model_decision.status,
        value=model_decision.value,
        evidence=evidence,
        related_fields=list(model_decision.related_fields),
        reason=model_decision.reason,
        failure_reason=model_decision.failure_reason,
    )


def _evidence_from_used_block_ids(
    *,
    field_name: str,
    used_block_ids: list[str],
    state: GraphState,
    status: str,
) -> FieldEvidence:
    if not used_block_ids:
        return _fallback_evidence_for_field(
            field_name=field_name,
            state=state,
            status=status,
        )

    blocks_by_id = {require_block_id(block): block for block in state.extraction_input.blocks}
    ordered_block_ids = _deduplicate_preserving_order([block_id for block_id in used_block_ids if block_id])
    unknown_block_ids = [block_id for block_id in ordered_block_ids if block_id not in blocks_by_id]
    if unknown_block_ids:
        raise ValueError(f"unknown used_block_ids: {', '.join(unknown_block_ids)}")

    blocks = [blocks_by_id[block_id] for block_id in ordered_block_ids]
    local_status = "model_resolved" if status == "resolved" else "model_failed"
    return FieldEvidence(
        field_name=field_name,
        relevant_block_ids=ordered_block_ids,
        evidence_texts=[block.text for block in blocks],
        evidence_refs=[
            FieldEvidenceRef(
                document_id=block.document_id,
                page=block.page_no,
                block_id=require_block_id(block),
            )
            for block in blocks
        ],
        local_status=local_status,
        local_notes=["按模型 used_block_ids 从标准化 blocks 绑定证据"],
    )


def _fallback_evidence_for_field(
    *,
    field_name: str,
    state: GraphState,
    status: str,
) -> FieldEvidence:
    if state.evidence_collection is not None:
        evidence = get_field_bundle(state.evidence_collection, field_name)
        if evidence is not None:
            return FieldEvidence(
                field_name=evidence.field_name,
                relevant_block_ids=list(evidence.relevant_block_ids),
                evidence_texts=list(evidence.evidence_texts),
                evidence_refs=list(evidence.evidence_refs),
                local_status=evidence.local_status,
                local_notes=[
                    *list(evidence.local_notes),
                    "模型未声明 used_block_ids，沿用 broad evidence",
                ],
            )
    local_status = "model_resolved" if status == "resolved" else "model_failed"
    return FieldEvidence(
        field_name=field_name,
        local_status=local_status,
        local_notes=["模型未声明 used_block_ids，且没有可沿用的 broad evidence"],
    )


def _merge_field_reference_records(
    current_records: list[FieldReferenceRecord],
    new_records: list[FieldReferenceRecord],
    *,
    related_fields: list[str],
) -> list[FieldReferenceRecord]:
    merged = list(current_records)
    seen = {
        (
            record.target_field_name,
            record.requested_field_name,
            record.found,
        )
        for record in merged
    }
    related_field_set = set(related_fields)
    for record in new_records:
        key = (
            record.target_field_name,
            record.requested_field_name,
            record.found,
        )
        if key in seen:
            continue
        record.used_in_final_decision = record.requested_field_name in related_field_set
        merged.append(record)
        seen.add(key)
    return merged


def _merge_lookup_records(
    current_records: list[LookupRecord],
    new_records: list[LookupRecord],
    *,
    used_block_ids: list[str],
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
        record.used_in_final_decision = bool(
            set(record.returned_block_ids) & set(used_block_ids)
        )
        merged.append(record)
        seen.add(key)
    return merged


def _refresh_tool_record_usage(decision: FieldDecision) -> FieldDecision:
    """按最终 evidence 重新标记工具记录是否支撑最终定案。"""

    final_block_ids = set(decision.evidence.relevant_block_ids)
    final_related_fields = set(decision.related_fields)
    for record in decision.field_reference_records:
        record.used_in_final_decision = record.requested_field_name in final_related_fields
    for record in decision.lookup_records:
        record.used_in_final_decision = bool(set(record.returned_block_ids) & final_block_ids)
    return decision


def _deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return deduplicated
