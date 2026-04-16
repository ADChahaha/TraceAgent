from __future__ import annotations

import re

from ocr_processor.schemas import ContentBlock


def build_markdown_from_blocks(blocks: list[ContentBlock]) -> str:
    fragments: list[str] = []

    for block in blocks:
        fragment = _build_markdown_fragment(block)
        if fragment:
            fragments.append(fragment)

    return "\n\n".join(fragments).strip()


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
