"""Convert MinerU content_list_v2 pages to traceable HTML."""

from __future__ import annotations

import html
import json
import re
from typing import Any


def build_html_from_content_list(pages: list[list[dict[str, Any]]]) -> str:
    """Build extraction HTML with stable ids and MinerU metadata."""

    return "\n".join(
        rendered
        for page_idx, page in enumerate(pages)
        if (rendered := render_page(page, page_idx))
    )


def build_display_html_from_content_list(pages: list[list[dict[str, Any]]]) -> str:
    """Build a self-contained display HTML document from MinerU pages."""

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Processed Document</title>
<style>
body {{ margin: 0; background: #f3f4f6; color: #171717; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
.page {{ background: #fff; margin: 0 0 20px; padding: 44px 56px; box-shadow: 0 1px 4px rgba(0,0,0,.12); position: relative; }}
.page-number {{ position: absolute; top: 12px; right: 18px; color: #737373; font-size: 12px; }}
.block {{ scroll-margin: 80px; }}
h1, h2, h3, h4, h5, h6 {{ line-height: 1.35; margin: 18px 0 10px; }}
h1 {{ font-size: 24px; text-align: center; }}
h2 {{ font-size: 20px; }}
h3 {{ font-size: 17px; }}
p, li {{ font-size: 14px; line-height: 1.75; }}
p {{ margin: 8px 0; }}
ul {{ margin: 8px 0 8px 22px; padding: 0; }}
figure {{ margin: 16px 0; }}
.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0; }}
td, th {{ border: 1px solid #737373; padding: 5px 7px; vertical-align: top; }}
.caption {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
.footnote {{ font-size: 12px; color: #525252; margin-top: 6px; }}
.block-label {{ font-size: 11px; color: #737373; text-transform: uppercase; letter-spacing: .04em; }}
.block:hover {{ outline: 2px solid #2563eb; outline-offset: 2px; }}
.dp-evidence-highlight {{ outline: 3px solid #f59e0b; background-color: #fff7cc; transition: background-color 160ms ease, outline-color 160ms ease; }}
</style>
</head>
<body>
<main>
{build_html_from_content_list(pages)}
</main>
</body>
</html>
"""


def build_blocks_from_content_list(pages: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Build backend evidence blocks using the same ids as rendered HTML."""

    blocks: list[dict[str, Any]] = []
    table_row_counter = 0
    for page_idx, page in enumerate(pages):
        page_no = page_idx + 1
        for block_idx, block in enumerate(page):
            if not should_render_block(block):
                continue
            block_id = f"p{page_no:03d}_b{block_idx:03d}"
            block_type = str(block.get("type", "unknown"))
            blocks.append(
                {
                    "block_id": block_id,
                    "text": block_text(block),
                    "page_no": page_no,
                    "bbox": block.get("bbox"),
                    "kind": normalize_block_kind(block_type),
                    "meta_info": {"mineru_type": block_type},
                }
            )
            if block_type in {"index", "list"}:
                blocks.extend(build_list_item_blocks(block, block_id, page_no))
            if block_type == "table":
                table_blocks, table_row_counter = build_table_row_blocks(
                    block,
                    block_id,
                    page_no,
                    table_row_counter,
                )
                blocks.extend(table_blocks)
    return blocks


def build_markdown_from_content_list(pages: list[list[dict[str, Any]]]) -> str:
    """Build plain markdown-like text for backend storage and audit views."""

    lines: list[str] = []
    for page in pages:
        for block in page:
            if not should_render_block(block):
                continue
            text = block_text(block)
            if not text:
                continue
            block_type = block.get("type")
            if block_type == "title":
                level = int(block.get("content", {}).get("level") or 2)
                level = max(1, min(level, 6))
                lines.append(f"{'#' * level} {text}")
            elif block_type in {"index", "list"}:
                for item in text.splitlines():
                    if item.strip():
                        lines.append(f"- {item.strip()}")
            else:
                lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def render_page(blocks: list[dict[str, Any]], page_idx: int) -> str:
    rendered = [
        render_block(block, page_idx, block_idx)
        for block_idx, block in enumerate(blocks)
        if should_render_block(block)
    ]
    if not rendered:
        return ""
    page_no = page_idx + 1
    return (
        f'<section class="page" id="page_{page_no:03d}" data-page="{page_no}">'
        f'<div class="page-number">Page {page_no}</div>'
        + "\n".join(rendered)
        + "</section>"
    )


def render_block(block: dict[str, Any], page_idx: int, block_idx: int) -> str:
    block_id = f"p{page_idx + 1:03d}_b{block_idx:03d}"
    block_type = block.get("type", "unknown")
    content = block.get("content", {})
    attrs = block_attrs(block_id, page_idx, block)

    if block_type == "title":
        level = int(content.get("level") or 2)
        level = max(1, min(level, 6))
        text = flatten_text(content.get("title_content"))
        return f"<h{level} {attrs}>{html.escape(text)}</h{level}>"

    if block_type == "paragraph":
        text = flatten_text(content.get("paragraph_content"))
        return f"<p {attrs}>{html.escape(text)}</p>"

    if block_type in {"index", "list"}:
        items = content.get("list_items") or []
        label = f'<div class="block-label">{html.escape(str(block_type))}</div>'
        return f"<section {attrs}>{label}{render_list_items(items, page_idx, block_id)}</section>"

    if block_type == "table":
        return render_table(block, block_id, page_idx, attrs)

    text = flatten_text(content)
    return f"<div {attrs}>{html.escape(text)}</div>"


def render_table(block: dict[str, Any], block_id: str, page_idx: int, attrs: str) -> str:
    content = block.get("content", {})
    caption = flatten_text(content.get("table_caption"))
    footnote = flatten_text(content.get("table_footnote"))
    table_html = ensure_table_evidence_ids(content.get("html") or "", block_id=block_id)
    pieces: list[str] = []
    if caption:
        pieces.append(f'<div class="caption">{html.escape(caption)}</div>')
    pieces.append(
        f'<div class="table-wrap" data-table-id="{block_id}" data-page="{page_idx + 1}">'
        f"{table_html}</div>"
    )
    if footnote:
        pieces.append(f'<div class="footnote">{html.escape(footnote)}</div>')
    return f"<figure {attrs}>{''.join(pieces)}</figure>"


def render_list_items(items: list[dict[str, Any]], page_idx: int, block_id: str) -> str:
    lis: list[str] = []
    for idx, item in enumerate(items):
        item_id = f"{block_id}_item_{idx:03d}"
        text = flatten_text(item.get("item_content"))
        lis.append(
            f'<li id="{item_id}" data-element-id="{item_id}" data-page="{page_idx + 1}" '
            f'data-type="list_item">{html.escape(text)}</li>'
        )
    list_id = f"{block_id}_list"
    return (
        f'<ul id="{list_id}" data-element-id="{list_id}" data-page="{page_idx + 1}" '
        f'data-type="list">'
        + "\n".join(lis)
        + "</ul>"
    )


def block_attrs(block_id: str, page_idx: int, block: dict[str, Any]) -> str:
    block_type = block.get("type", "unknown")
    classes = f"block block-{html.escape(str(block_type))}"
    attrs = [
        f'id="{block_id}"',
        f'class="{classes}"',
        f'data-element-id="{block_id}"',
        f'data-page="{page_idx + 1}"',
        f'data-type="{html.escape(str(block_type))}"',
    ]
    if block_type == "title":
        level = block.get("content", {}).get("level")
        if level is not None:
            attrs.append(f'data-level="{html.escape(str(level))}"')
    bbox = block.get("bbox")
    if bbox:
        attrs.append(f"data-bbox='{html.escape(json.dumps(bbox, ensure_ascii=False))}'")
    return " ".join(attrs)


def should_render_block(block: dict[str, Any]) -> bool:
    """Return true only for blocks that have visible text or table structure."""

    block_type = str(block.get("type", "unknown"))
    if block_type == "page_number":
        return False
    if block_type == "table":
        content = block.get("content", {})
        return bool(content.get("html") or flatten_text(content.get("table_caption")) or flatten_text(content.get("table_footnote")))
    if "image" in block_type or block_type in {"interline_equation", "inline_equation"}:
        return False
    content = block.get("content", {})
    if isinstance(content, dict) and content.get("image_source") and not any(
        content.get(key)
        for key in (
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
    ):
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
        return "".join(
            flatten_text(value)
            for value in parts.values()
            if isinstance(value, (str, list, dict))
        )
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
        return "\n".join(
            flatten_text(item.get("item_content"))
            for item in items
            if isinstance(item, dict)
        )
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


def build_list_item_blocks(
    block: dict[str, Any],
    block_id: str,
    page_no: int,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    content = block.get("content", {})
    for item_idx, item in enumerate(content.get("list_items") or []):
        if not isinstance(item, dict):
            continue
        text = flatten_text(item.get("item_content"))
        blocks.append(
            {
                "block_id": f"{block_id}_item_{item_idx:03d}",
                "text": text,
                "page_no": page_no,
                "bbox": None,
                "kind": "list_item",
                "meta_info": {"parent_block_id": block_id, "mineru_type": "list_item"},
            }
        )
    return blocks


def build_table_row_blocks(
    block: dict[str, Any],
    block_id: str,
    page_no: int,
    row_counter: int,
) -> tuple[list[dict[str, Any]], int]:
    content = block.get("content", {})
    rows = extract_table_rows(ensure_table_evidence_ids(content.get("html") or "", block_id=block_id))
    blocks: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        row_counter += 1
        blocks.append(
            {
                "block_id": row["id"] or f"{block_id}_tr_{row_index:03d}",
                "text": row["text"],
                "page_no": page_no,
                "bbox": None,
                "kind": "table_header" if row_index == 0 else "table_row",
                "meta_info": {
                    "parent_block_id": block_id,
                    "mineru_type": "table_row",
                    "row_index": row_index,
                },
            }
        )
    return blocks, row_counter


def normalize_block_kind(block_type: str) -> str:
    if block_type == "title":
        return "heading"
    if block_type == "paragraph":
        return "text"
    if block_type in {"index", "list"}:
        return "list"
    if block_type == "table":
        return "table"
    if block_type == "page_footnote":
        return "footnote"
    return block_type


def ensure_table_evidence_ids(table_html: str, *, block_id: str) -> str:
    """Inject deterministic ids into table/tr tags that do not already have one."""

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
        return f"<{tag_name} id=\"{generated_id}\"{attrs}>"

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
