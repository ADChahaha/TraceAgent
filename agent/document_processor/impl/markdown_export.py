from __future__ import annotations

import re
from typing import Any

from document_processor.schemas import ContentBlock


def build_markdown_items_from_blocks(blocks: list[ContentBlock]) -> list[str]:
    items: list[str] = []

    for index, block in enumerate(blocks):
        item = _build_markdown_fragment(block)
        block.meta_info["block_id"] = f"blk_{index + 1:04d}"
        block.meta_info["md"] = item
        items.append(item)

    return items


def build_markdown_from_blocks(blocks: list[ContentBlock]) -> str:
    return "\n\n".join(item for item in build_markdown_items_from_blocks(blocks) if item).strip()


def build_meta_info_from_blocks(
    blocks: list[ContentBlock],
    *,
    engine: str,
    fallback_used: bool,
) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    for block in blocks:
        kind_counts[block.kind] = kind_counts.get(block.kind, 0) + 1

    return {
        "engine": engine,
        "fallback_used": fallback_used,
        "block_count": len(blocks),
        "md_item_count": len(blocks),
        "has_table": kind_counts.get("table", 0) > 0,
        "kind_counts": kind_counts,
    }


def _build_markdown_fragment(block: ContentBlock) -> str:
    text = block.text.strip()
    if not text:
        return ""

    kind = block.kind.strip().lower()
    if kind == "table":
        return text
    if kind == "heading":
        return f"# {text}"
    if kind == "subheading":
        return f"## {text}"
    if kind == "list_item":
        return _build_list_item(text)

    return _normalize_text_block(text)


def _build_list_item(text: str) -> str:
    stripped = text.lstrip("-* ").strip()
    if not stripped:
        return ""
    return f"- {stripped}"


def _normalize_text_block(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()
