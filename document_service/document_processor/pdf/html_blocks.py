"""MinerU 内容块提取、目录页识别、标题层级推断与文本归一化。"""

from __future__ import annotations

import re
from typing import Any

from document_service.document_processor.pdf.html_tables import extract_text_from_table_html


def markdown_blocks(pages: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """展平 MinerU 页面中的可渲染块并附带版面特征。"""
    rendered_blocks: list[dict[str, Any]] = []
    for page_idx, page in enumerate(pages):
        page_no = page_idx + 1
        for block_idx, block in enumerate(page):
            if not should_render_block(block):
                continue
            text = block_text(block)
            if not text:
                continue
            rendered_blocks.append(markdown_block_from_source(block, page_no, block_idx))
    return rendered_blocks


def classify_markdown_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一完成目录页识别与正文小标题降级，大章节标题直接信任 MinerU content.level。"""
    toc_pages = detect_table_of_contents_pages(blocks)
    for block in blocks:
        is_toc_entry = block["page_no"] in toc_pages and not is_table_of_contents_heading(block)
        block["is_toc_entry"] = is_toc_entry
        block["heading_level"] = infer_markdown_heading_level(block)
        if is_toc_entry and not is_table_of_contents_heading(block):
            block["heading_level"] = None
    return blocks


def detect_table_of_contents_pages(blocks: list[dict[str, Any]]) -> set[int]:
    toc_pages: set[int] = set()
    for block in blocks:
        if is_table_of_contents_heading(block):
            toc_pages.add(int(block["page_no"]))
    return toc_pages


def is_table_of_contents_heading(block: dict[str, Any]) -> bool:
    if block.get("type") != "title":
        return False
    text = normalize_table_of_contents_text(block.get("text") or "")
    return text in {"目次", "目録", "もくじ", "contents", "tableofcontents"}


def normalize_table_of_contents_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_inline_space(text)).lower()


def infer_markdown_heading_level(block: dict[str, Any]) -> int | None:
    if block.get("type") != "title":
        return None
    if is_table_of_contents_heading(block):
        return markdown_title_level(block)
    if markdown_is_body_subheading(block):
        return None
    return markdown_title_level(block)


def markdown_heading_level(block: dict[str, Any]) -> int | None:
    level = block.get("heading_level")
    if level is None:
        return None
    return max(1, min(int(level), 6))


def markdown_block_from_source(block: dict[str, Any], page_no: int, block_idx: int) -> dict[str, Any]:
    text = block_text(block)
    return {
        "block": block,
        "page_no": page_no,
        "block_idx": block_idx,
        "type": str(block.get("type", "unknown")),
        "text": text,
        "features": markdown_layout_features(block, text),
    }


def markdown_title_level(block: dict[str, Any]) -> int:
    source = block["block"]
    source_level = source.get("content", {}).get("level")
    if source_level is not None:
        return max(1, min(int(source_level), 6))
    return 2


def markdown_is_body_subheading(block: dict[str, Any]) -> bool:
    text = normalize_inline_space(block.get("text") or "")
    if not text or text in {"目次", "募集要項"}:
        return False
    patterns = (
        r"^<<.+>>$",
        r"^【.+】$",
        r"^[（(][0-9０-９一二三四五六七八九十A-Za-z]+[)）]\s*",
        r"^[0-9０-９]+[）)]\s*",
        r"^[A-Z]$",
        r"^[a-z]$",
    )
    if any(re.match(pattern, text) for pattern in patterns):
        return True
    source_level = int(block["block"].get("content", {}).get("level") or 0)
    if source_level >= 2 and len(re.sub(r"\s+", "", text)) <= 12:
        if not re.match(r"^\d+[．.]\s*", text):
            return True
    return False


def markdown_layout_features(block: dict[str, Any], text: str) -> list[int]:
    bbox = block.get("bbox") or [0, 0, 0, 0]
    x0, y0, x1, y1 = [int(value or 0) for value in bbox[:4]]
    visible_text = re.sub(r"<[^>]+>", "", text)
    chars = len(re.sub(r"\s+", "", visible_text))
    line_count = max(1, text.count("\n") + 1)
    return [y1 - y0, x1 - x0, chars, line_count, x0, y0]


def should_render_block(block: dict[str, Any]) -> bool:
    """仅保留含可读文本或表格结构的块，过滤页眉页脚与纯图片/公式块。"""
    block_type = str(block.get("type", "unknown"))
    if block_type in {"page_header", "page_number", "page_footer"}:
        return False
    if block_type == "table":
        content = block.get("content", {})
        return bool(
            content.get("html")
            or flatten_text(content.get("table_caption"))
            or flatten_text(content.get("table_footnote"))
        )
    if "image" in block_type or block_type in {"interline_equation", "inline_equation"}:
        return False
    content = block.get("content", {})
    text_keys = (
        "title_content",
        "paragraph_content",
        "list_items",
        "table_caption",
        "table_footnote",
        "html",
        "page_footnote_content",
        "text",
        "content",
    )
    if isinstance(content, dict) and content.get("image_source") and not any(content.get(k) for k in text_keys):
        return False
    return bool(block_text(block).strip())


def flatten_text(parts: Any) -> str:
    if parts is None:
        return ""
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        return "".join(flatten_text(item) for item in parts)
    if isinstance(parts, dict):
        if isinstance(parts.get("content"), str):
            return parts["content"]
        return "".join(flatten_text(value) for value in parts.values() if isinstance(value, (str, list, dict)))
    return ""


def block_text(block: dict[str, Any]) -> str:
    block_type = block.get("type")
    content = block.get("content", {})
    if block_type == "title":
        return flatten_text(content.get("title_content"))
    if block_type == "paragraph":
        return flatten_text(content.get("paragraph_content"))
    if block_type in {"index", "list"}:
        items = content.get("list_items") or []
        return "\n".join(flatten_text(item.get("item_content")) for item in items if isinstance(item, dict))
    if block_type == "table":
        return table_text(content)
    if isinstance(content, dict):
        for key in ("page_footnote_content", "text", "content"):
            value = content.get(key)
            if value is not None:
                text = flatten_text(value)
                if text:
                    return text
    return flatten_text(content)


def table_text(content: dict[str, Any]) -> str:
    parts = [
        flatten_text(content.get("table_caption")),
        extract_text_from_table_html(content.get("html") or ""),
        flatten_text(content.get("table_footnote")),
    ]
    return "\n".join(part for part in parts if part)


def normalize_inline_space(text: str) -> str:
    return " ".join(text.split())
