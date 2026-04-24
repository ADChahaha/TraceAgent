"""resolution 阶段使用的内部辅助工具。"""

from __future__ import annotations

from file_extraction_agent.impl.schemas import (
    EvidenceCollection,
    FieldEvidence,
    LookupRecord,
    LookupResult,
)
from file_extraction_agent.schemas import FieldEvidenceRef, NormalizedBlock


def get_field_bundle(
    evidence_collection: EvidenceCollection,
    field_name: str,
) -> FieldEvidence | None:
    """按字段名读取 broad 阶段已有的 evidence bundle。"""

    for field_evidence in evidence_collection.fields:
        if field_evidence.field_name == field_name:
            return field_evidence
    return None


def lookup_blocks_for_field(
    *,
    blocks: list[NormalizedBlock],
    target_field_name: str,
    query_reason: str,
    lookup_hints: list[str] | None = None,
    top_k: int = 3,
) -> LookupResult:
    """按字段名和 hints 从全量标准化 blocks 中补查相关内容。"""

    hints = [hint for hint in (lookup_hints or []) if hint]
    scored_blocks = [
        (score, index, block)
        for index, block in enumerate(blocks)
        if (score := _score_block(block, target_field_name, hints)) > 0
    ]
    scored_blocks.sort(key=lambda item: (-item[0], item[1]))
    matched_blocks = [block for _, _, block in scored_blocks[:top_k]]

    record = LookupRecord(
        target_field_name=target_field_name,
        lookup_reason=query_reason,
        lookup_hints=hints,
        returned_block_ids=[_block_id(block) for block in matched_blocks],
        returned_refs=[_block_ref(block) for block in matched_blocks],
    )
    return LookupResult(matched_blocks=matched_blocks, record=record)


def _score_block(
    block: NormalizedBlock,
    target_field_name: str,
    lookup_hints: list[str],
) -> int:
    text = block.text.lower()
    score = 0
    for token in [target_field_name, *lookup_hints]:
        normalized_token = token.lower()
        if normalized_token and normalized_token in text:
            score += 1
    return score


def _block_id(block: NormalizedBlock) -> str:
    if block.block_id:
        return block.block_id
    meta_block_id = block.meta_info.get("block_id")
    if meta_block_id:
        return str(meta_block_id)
    return f"{block.document_id}:{block.page_no or 0}:{abs(hash(block.text))}"


def _block_ref(block: NormalizedBlock) -> FieldEvidenceRef:
    return FieldEvidenceRef(
        document_id=block.document_id,
        page=block.page_no,
        block_id=_block_id(block),
    )
