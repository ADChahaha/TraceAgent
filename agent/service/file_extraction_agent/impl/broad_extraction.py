"""service.file_extraction_agent 的 broad extraction 节点。"""

from __future__ import annotations

from typing import Any

from service.file_extraction_agent.impl.block_ids import require_block_id
from service.file_extraction_agent.impl.prompts import build_broad_extraction_messages
from service.file_extraction_agent.impl.schemas import EvidenceCollection
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
    duplicated_fields = sorted(
        {
            field_name
            for field_name in returned_fields
            if returned_fields.count(field_name) > 1
        }
    )
    if duplicated_fields:
        raise ValueError(f"duplicate broad evidence fields: {', '.join(duplicated_fields)}")

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
