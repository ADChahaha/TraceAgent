from __future__ import annotations

from file_extraction_agent.impl.schemas import EvidenceCollection, FieldEvidence
from file_extraction_agent.impl.tools import get_field_bundle, lookup_blocks_for_field
from file_extraction_agent.schemas import NormalizedBlock


def test_get_field_bundle_returns_named_broad_evidence():
    evidence = FieldEvidence(
        field_name="amount",
        relevant_block_ids=["b-1"],
        evidence_texts=["金额：100.00"],
        local_status="evidence_found",
    )
    collection = EvidenceCollection(fields=[evidence])

    assert get_field_bundle(collection, "amount") is evidence
    assert get_field_bundle(collection, "missing") is None


def test_lookup_blocks_for_field_uses_hints_and_keeps_refs():
    blocks = [
        NormalizedBlock(document_id="doc-1", block_id="b-1", text="无关内容", page_no=1),
        NormalizedBlock(document_id="doc-1", block_id="b-2", text="应付金额：100.00 元", page_no=2),
    ]

    result = lookup_blocks_for_field(
        blocks=blocks,
        target_field_name="amount",
        query_reason="证据缺失，按 lookup hints 补查",
        lookup_hints=["应付金额"],
        top_k=1,
    )

    assert result.record.target_field_name == "amount"
    assert result.record.returned_block_ids == ["b-2"]
    assert result.record.returned_refs[0].document_id == "doc-1"
    assert result.record.returned_refs[0].page == 2
    assert result.matched_blocks == [blocks[1]]
