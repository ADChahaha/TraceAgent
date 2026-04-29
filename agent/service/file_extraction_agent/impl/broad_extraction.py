"""service.file_extraction_agent 的 broad extraction 节点。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.block_ids import require_block_id
from service.file_extraction_agent.impl.prompts import build_broad_extraction_messages
from service.file_extraction_agent.impl.schemas import EvidenceCollection, FieldEvidence
from service.file_extraction_agent.schemas import FieldEvidenceRef
from service.file_extraction_agent.impl.state import GraphState


def run_broad_extraction(
    *,
    state: GraphState,
    extractor_client: Any,
) -> GraphState:
    """执行第一阶段字段证据预选，并把结果写回图状态。"""

    evidence_collection = extractor_client.invoke(
        output_schema=EvidenceCollection,
        messages=build_broad_extraction_messages(state.extraction_input),
    )
    _validate_evidence_collection(
        evidence_collection=evidence_collection,
        state=state,
    )
    evidence_collection = _merge_duplicate_field_evidence(evidence_collection)
    state.evidence_collection = evidence_collection
    return state


def _validate_evidence_collection(
    *,
    evidence_collection: EvidenceCollection,
    state: GraphState,
) -> None:
    expected_fields = [field.field_name for field in state.extraction_input.task_spec.fields]
    expected_field_set = set(expected_fields)

    returned_fields = [field_evidence.field_name for field_evidence in evidence_collection.fields]

    returned_field_set = set(returned_fields)
    unknown_fields = sorted(returned_field_set - expected_field_set)
    if unknown_fields:
        raise ValueError(f"unknown broad evidence fields: {', '.join(unknown_fields)}")

    missing_fields = [field_name for field_name in expected_fields if field_name not in returned_field_set]
    if missing_fields:
        raise ValueError(f"missing broad evidence fields: {', '.join(missing_fields)}")

    known_block_ids = {require_block_id(block) for block in state.extraction_input.blocks}
    unknown_block_ids: set[str] = set()
    missing_ref_block_ids: list[str] = []
    for field_evidence in evidence_collection.fields:
        unknown_block_ids.update(
            block_id
            for block_id in field_evidence.relevant_block_ids
            if block_id and block_id not in known_block_ids
        )
        for ref_index, ref in enumerate(field_evidence.evidence_refs):
            if not ref.block_id:
                missing_ref_block_ids.append(f"{field_evidence.field_name}[{ref_index}]")
                continue
            if ref.block_id not in known_block_ids:
                unknown_block_ids.add(ref.block_id)

    if missing_ref_block_ids:
        missing_refs = ", ".join(missing_ref_block_ids)
        raise ValueError(f"broad evidence refs missing block_id: {missing_refs}")

    if unknown_block_ids:
        unknown = ", ".join(sorted(unknown_block_ids))
        raise ValueError(f"unknown broad evidence block ids: {unknown}")


def _merge_duplicate_field_evidence(
    evidence_collection: EvidenceCollection,
) -> EvidenceCollection:
    returned_fields = [field_evidence.field_name for field_evidence in evidence_collection.fields]
    if len(returned_fields) == len(set(returned_fields)):
        return evidence_collection

    merged_by_field: dict[str, FieldEvidence] = {}
    ordered_fields: list[str] = []

    for field_evidence in evidence_collection.fields:
        existing = merged_by_field.get(field_evidence.field_name)
        if existing is None:
            merged_by_field[field_evidence.field_name] = field_evidence
            ordered_fields.append(field_evidence.field_name)
            continue

        merged_by_field[field_evidence.field_name] = FieldEvidence(
            field_name=existing.field_name,
            relevant_block_ids=_deduplicate_preserving_order(
                [*existing.relevant_block_ids, *field_evidence.relevant_block_ids]
            ),
            evidence_texts=_deduplicate_preserving_order(
                [*existing.evidence_texts, *field_evidence.evidence_texts]
            ),
            evidence_refs=_deduplicate_refs(
                [*existing.evidence_refs, *field_evidence.evidence_refs]
            ),
            local_status=_merge_local_status(existing.local_status, field_evidence.local_status),
            local_notes=_deduplicate_preserving_order(
                [*existing.local_notes, *field_evidence.local_notes]
            ),
        )

    return EvidenceCollection(fields=[merged_by_field[field_name] for field_name in ordered_fields])


def _merge_local_status(current: str, incoming: str) -> str:
    if current == "evidence_found" or incoming != "evidence_found":
        return current
    return incoming


def _deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduplicated.append(value)
    return deduplicated


def _deduplicate_refs(refs: list[FieldEvidenceRef]) -> list[FieldEvidenceRef]:
    seen: set[tuple[str, int | None, str | None, str | None]] = set()
    deduplicated: list[FieldEvidenceRef] = []
    for ref in refs:
        key = (ref.document_id, ref.page, ref.span, ref.block_id)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(ref)
    return deduplicated
