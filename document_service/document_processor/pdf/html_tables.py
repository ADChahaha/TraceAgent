"""MinerU 表格 HTML 规范化、证据 ID 注入与单元格纯文本提取。"""

from __future__ import annotations

import html
import re
from typing import Any


def render_table(block: dict[str, Any], block_id: str, page_idx: int, attrs: str, *, flatten_text) -> str:
    content = block.get("content", {})
    caption = flatten_text(content.get("table_caption"))
    footnote = flatten_text(content.get("table_footnote"))
    table_html = ensure_table_evidence_ids(content.get("html") or "", block_id=block_id)
    table_html = ensure_table_root(table_html, attrs)
    table_html = ensure_table_caption(table_html, block_id, page_idx, caption)
    pieces = [table_html]
    if footnote:
        pieces.append(f'<div class="footnote">{html.escape(footnote)}</div>')
    return "".join(pieces)


def ensure_table_root(table_html: str, attrs: str) -> str:
    """将块级 id 与元数据挂到 table 根节点。"""
    if not table_html.strip():
        return f"<table {attrs}></table>"
    return re.sub(
        r"<\s*table\b[^>]*>",
        f"<table {attrs}>",
        table_html,
        count=1,
        flags=re.IGNORECASE,
    )


def ensure_table_caption(
    table_html: str,
    block_id: str,
    page_idx: int,
    caption: str,
) -> str:
    caption_attrs = (
        f'id="{block_id}_caption" data-element-id="{block_id}_caption" '
        f'data-page="{page_idx + 1}" data-type="caption"'
    )
    if re.search(r"<\s*caption\b", table_html, flags=re.IGNORECASE):
        return re.sub(
            r"<\s*caption\b[^>]*>",
            f"<caption {caption_attrs}>",
            table_html,
            count=1,
            flags=re.IGNORECASE,
        )
    if not caption:
        return table_html
    caption_html = f"<caption {caption_attrs}>{html.escape(caption)}</caption>"
    return re.sub(
        r"(<\s*table\b[^>]*>)",
        lambda match: f"{match.group(1)}{caption_html}",
        table_html,
        count=1,
        flags=re.IGNORECASE,
    )


def ensure_table_evidence_ids(table_html: str, *, block_id: str) -> str:
    """为未带 id 的 table/tr 标签注入确定性证据 ID。"""
    counters = {"table": 0, "tr": 0}

    def replace(match: re.Match[str]) -> str:
        slash, tag_name, attrs = match.groups()
        if slash:
            return match.group(0)
        if re.search(r"\bid\s*=", attrs, flags=re.IGNORECASE):
            return match.group(0)
        tag = tag_name.lower()
        counters[tag] += 1
        if tag == "table":
            generated_id = (
                f"{block_id}_table"
                if counters[tag] == 1
                else f"{block_id}_table_{counters[tag] - 1:03d}"
            )
        else:
            generated_id = f"{block_id}_tr_{counters[tag] - 1:03d}"
        return f'<{tag_name} id="{generated_id}"{attrs}>'

    return re.sub(
        r"<\s*(/?)\s*(table|tr)\b([^>]*)>",
        replace,
        table_html,
        flags=re.IGNORECASE,
    )


def extract_table_row_texts(table_html: str) -> list[str]:
    return [row["text"] for row in extract_table_rows(table_html)]


def extract_table_rows(table_html: str) -> list[dict[str, str]]:
    parsed_rows: list[dict[str, str]] = []
    for row_match in re.finditer(
        r"<\s*tr\b([^>]*)>(.*?)<\s*/\s*tr\s*>",
        table_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        attrs = row_match.group(1)
        row_html = row_match.group(2)
        cells = [
            html.unescape(strip_html_tags(cell_match.group(2))).strip()
            for cell_match in re.finditer(
                r"<\s*(td|th)\b[^>]*>(.*?)<\s*/\s*\1\s*>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
        row_text = " | ".join(" ".join(cell.split()) for cell in cells if cell)
        if row_text:
            id_match = re.search(r'\bid\s*=\s*["\']?([^"\'\s>]+)', attrs, flags=re.IGNORECASE)
            parsed_rows.append(
                {
                    "id": id_match.group(1) if id_match else "",
                    "text": row_text,
                }
            )
    return parsed_rows


def extract_text_from_table_html(table_html: str) -> str:
    return "\n".join(extract_table_row_texts(table_html))


def strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)
