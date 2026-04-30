from __future__ import annotations

import pytest

from service.file_extraction_agent.schemas import NormalizedBlock


def test_validate_blocks_contract_accepts_traceable_text_and_table_blocks():
    from service.file_extraction_agent.block_contract import validate_blocks_contract

    blocks = [
        NormalizedBlock(
            document_id="doc-1",
            block_id="b-text",
            kind="text",
            text="发票号：INV-001",
            page_no=1,
        ),
        NormalizedBlock(
            document_id="doc-1",
            block_id="b-table",
            kind="table",
            text="| name | amount |\n|---|---|\n| A | 100 |",
            page_no=2,
        ),
    ]

    assert validate_blocks_contract(blocks) is None


def test_validate_blocks_contract_rejects_empty_input_and_missing_trace_fields():
    from service.file_extraction_agent.block_contract import validate_blocks_contract

    with pytest.raises(ValueError, match="blocks must be a non-empty list"):
        validate_blocks_contract([])

    with pytest.raises(ValueError, match="document_id is required at index 0"):
        validate_blocks_contract(
            [
                {
                    "document_id": "",
                    "block_id": "b-1",
                    "kind": "text",
                    "text": "内容",
                }
            ]
        )

    with pytest.raises(ValueError, match="block_id is required at index 0"):
        validate_blocks_contract(
            [
                {
                    "document_id": "doc-1",
                    "block_id": "",
                    "kind": "text",
                    "text": "内容",
                }
            ]
        )


def test_validate_blocks_contract_rejects_duplicate_block_ids():
    from service.file_extraction_agent.block_contract import validate_blocks_contract

    blocks = [
        NormalizedBlock(document_id="doc-1", block_id="b-dup", text="内容 A"),
        NormalizedBlock(document_id="doc-1", block_id="b-dup", text="内容 B"),
    ]

    with pytest.raises(ValueError, match="duplicate block_id: b-dup"):
        validate_blocks_contract(blocks)


def test_validate_blocks_contract_rejects_unreadable_table_blocks():
    from service.file_extraction_agent.block_contract import validate_blocks_contract

    blocks = [
        NormalizedBlock(
            document_id="doc-1",
            block_id="b-table",
            kind="table",
            text="没有任何 markdown table 行",
        )
    ]

    with pytest.raises(ValueError, match="table block cannot be converted to row text"):
        validate_blocks_contract(blocks)
