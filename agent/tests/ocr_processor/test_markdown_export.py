from __future__ import annotations

from ocr_processor.markdown_export import build_markdown_from_blocks
from ocr_processor.schemas import ContentBlock


def test_build_markdown_from_blocks_joins_text_and_table_blocks():
    blocks = [
        ContentBlock(text="Intro paragraph", kind="text"),
        ContentBlock(
            text="| Name | Score |\n| --- | --- |\n| Ada | 100 |",
            kind="table",
        ),
        ContentBlock(text="Closing note", kind="text"),
    ]

    markdown = build_markdown_from_blocks(blocks)

    assert markdown == (
        "Intro paragraph\n\n"
        "| Name | Score |\n| --- | --- |\n| Ada | 100 |\n\n"
        "Closing note"
    )


def test_build_markdown_from_blocks_supports_basic_semantic_kinds():
    blocks = [
        ContentBlock(text="Summary", kind="heading"),
        ContentBlock(text="First bullet", kind="list_item"),
        ContentBlock(text="Second bullet", kind="list_item"),
    ]

    markdown = build_markdown_from_blocks(blocks)

    assert markdown == "# Summary\n\n- First bullet\n\n- Second bullet"
