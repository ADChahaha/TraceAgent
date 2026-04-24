"""file_extraction_agent 的 broad extraction 节点。"""

from __future__ import annotations

from typing import Any

from file_extraction_agent.impl.prompts import build_broad_extraction_messages
from file_extraction_agent.impl.schemas import EvidenceCollection
from file_extraction_agent.impl.state import GraphState
from file_extraction_agent.schemas import NormalizedBlock


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

    known_block_ids = {_block_id(block) for block in state.extraction_input.blocks}
    unknown_block_ids: set[str] = set()
    for field_evidence in evidence_collection.fields:
        unknown_block_ids.update(
            block_id
            for block_id in field_evidence.relevant_block_ids
            if block_id and block_id not in known_block_ids
        )
        unknown_block_ids.update(
            ref.block_id
            for ref in field_evidence.evidence_refs
            if ref.block_id and ref.block_id not in known_block_ids
        )

    if unknown_block_ids:
        unknown = ", ".join(sorted(unknown_block_ids))
        raise ValueError(f"unknown broad evidence block ids: {unknown}")


def _block_id(block: NormalizedBlock) -> str:
    if block.block_id:
        return block.block_id
    meta_block_id = block.meta_info.get("block_id")
    if meta_block_id:
        return str(meta_block_id)
    return f"{block.document_id}:{block.page_no or 0}:{abs(hash(block.text))}"
