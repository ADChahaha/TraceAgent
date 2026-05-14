"""Convert MinerU content_list_v2 pages to traceable HTML."""

from __future__ import annotations

import html
import hashlib
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


def build_semantic_document_from_content_list(
    pages: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build section/block/inline semantic structure from MinerU pages."""

    return build_semantic_document_from_blocks(build_blocks_from_content_list(pages))


def build_semantic_document_from_blocks(
    source_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build section/block/inline semantic structure from evidence blocks."""

    sections: list[dict[str, Any]] = []
    semantic_blocks: list[dict[str, Any]] = []
    inlines: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_lead_in_id: str | None = None
    seen_inline_ids: dict[str, int] = {}

    for source_block in source_blocks:
        if is_noise_semantic_block(source_block):
            continue
        if source_block.get("kind") == "list":
            continue
        text = normalize_inline_space(source_block.get("text") or "")
        if not text:
            continue
        block_id = str(source_block["block_id"])
        block_type = semantic_block_type(source_block, text)
        if block_type == "heading":
            level = heading_level(text, len(sections))
            current_section = {
                "section_id": f"sec_{len(sections) + 1:03d}",
                "title": text,
                "level": level,
                "source_heading_block_id": block_id,
                "page_no": source_block.get("page_no"),
                "bbox": source_block.get("bbox"),
                "block_ids": [],
                "text": "",
            }
            sections.append(current_section)
            current_lead_in_id = None
        elif current_section is None:
            current_section = {
                "section_id": "sec_001",
                "title": "Document",
                "level": 1,
                "source_heading_block_id": None,
                "page_no": source_block.get("page_no"),
                "bbox": None,
                "block_ids": [],
                "text": "",
            }
            sections.append(current_section)

        section_id = current_section["section_id"]
        clause_marker = extract_clause_marker(text)
        parent_block_id = semantic_parent_block_id(
            block_type=block_type,
            clause_marker=clause_marker,
            current_lead_in_id=current_lead_in_id,
        )
        inline_items = build_inlines_for_block(
            block_id,
            text,
            block_type,
            clause_marker,
            seen_inline_ids=seen_inline_ids,
        )
        semantic_block = {
            "block_id": block_id,
            "section_id": section_id,
            "parent_block_id": parent_block_id,
            "type": block_type,
            "clause_marker": clause_marker,
            "text": text,
            "page_no": source_block.get("page_no"),
            "bbox": source_block.get("bbox"),
            "source_kind": source_block.get("kind"),
            "source_mineru_type": (source_block.get("meta_info") or {}).get(
                "mineru_type"
            ),
            "inline_ids": [item["inline_id"] for item in inline_items],
        }
        semantic_blocks.append(semantic_block)
        inlines.extend(inline_items)
        current_section["block_ids"].append(block_id)
        current_section["text"] = append_section_text(current_section["text"], text, block_type)

        if block_type == "lead_in":
            current_lead_in_id = block_id
        elif block_type not in {"clause", "list_item"}:
            current_lead_in_id = None

    return {"sections": sections, "blocks": semantic_blocks, "inlines": inlines}


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
    rendered = render_blocks_with_sections(blocks, page_idx)
    if not rendered:
        return ""
    page_no = page_idx + 1
    return (
        f'<section class="page" id="page_{page_no:03d}" data-page="{page_no}">'
        + "\n".join(rendered)
        + "</section>"
    )


def render_blocks_with_sections(blocks: list[dict[str, Any]], page_idx: int) -> list[str]:
    rendered: list[str] = []
    open_section = False
    open_subsection = False
    for block_idx, block in enumerate(blocks):
        if not should_render_block(block):
            continue
        block_id = f"p{page_idx + 1:03d}_b{block_idx:03d}"
        if is_section_heading(block):
            if open_subsection:
                rendered.append("</section>")
                open_subsection = False
            if open_section:
                rendered.append("</section>")
            rendered.append(
                f'<section class="section section-level-2" id="{block_id}_section" '
                f'data-section-level="2" data-page="{page_idx + 1}" '
                f'aria-labelledby="{block_id}">'
            )
            open_section = True
        elif is_subsection_heading(block):
            if open_subsection:
                rendered.append("</section>")
            rendered.append(
                f'<section class="subsection subsection-level-3" id="{block_id}_subsection" '
                f'data-section-level="3" data-page="{page_idx + 1}" '
                f'aria-labelledby="{block_id}">'
            )
            open_subsection = True
        rendered.append(render_block(block, page_idx, block_idx))
    if open_subsection:
        rendered.append("</section>")
    if open_section:
        rendered.append("</section>")
    return rendered


def is_section_heading(block: dict[str, Any]) -> bool:
    return heading_level_from_block(block) == 2


def is_subsection_heading(block: dict[str, Any]) -> bool:
    return heading_level_from_block(block) == 3


def heading_level_from_block(block: dict[str, Any]) -> int | None:
    if block.get("type") != "title":
        return None
    return int(block.get("content", {}).get("level") or 2)


def render_block(block: dict[str, Any], page_idx: int, block_idx: int) -> str:
    block_id = f"p{page_idx + 1:03d}_b{block_idx:03d}"
    block_type = block.get("type", "unknown")
    content = block.get("content", {})
    attrs = block_attrs(block_id, page_idx, block)

    if block_type == "title":
        level = int(content.get("level") or 2)
        level = max(1, min(level, 6))
        text = flatten_text(content.get("title_content"))
        if level >= 4:
            return f"<p {attrs}>{html.escape(text)}</p>"
        return f"<h{level} {attrs}>{html.escape(text)}</h{level}>"

    if block_type == "paragraph":
        text = flatten_text(content.get("paragraph_content"))
        return f"<p {attrs}>{html.escape(text)}</p>"

    if block_type in {"index", "list"}:
        items = content.get("list_items") or []
        return render_list_items(items, page_idx, block_id, attrs)

    if block_type == "table":
        return render_table(block, block_id, page_idx, attrs)

    text = flatten_text(content)
    return f"<div {attrs}>{html.escape(text)}</div>"


def render_table(block: dict[str, Any], block_id: str, page_idx: int, attrs: str) -> str:
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
    """Put the block id and metadata on the table element itself."""

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


def render_list_items(
    items: list[dict[str, Any]],
    page_idx: int,
    block_id: str,
    attrs: str,
) -> str:
    lis: list[str] = []
    for idx, item in enumerate(items):
        item_id = f"{block_id}_item_{idx:03d}"
        text = flatten_text(item.get("item_content"))
        lis.append(
            f'<li id="{item_id}" data-element-id="{item_id}" data-page="{page_idx + 1}" '
            f'data-type="list_item">{html.escape(text)}</li>'
        )
    return f"<ul {attrs}>" + "\n".join(lis) + "</ul>"


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
    if block_type in {"page_header", "page_number", "page_footer"}:
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


def is_noise_semantic_block(block: dict[str, Any]) -> bool:
    kind = block.get("kind")
    mineru_type = (block.get("meta_info") or {}).get("mineru_type")
    return kind in {"page_header", "page_number", "page_footer"} or mineru_type in {
        "page_header",
        "page_number",
        "page_footer",
    }


def normalize_inline_space(text: str) -> str:
    return " ".join(text.split())


def semantic_block_type(block: dict[str, Any], text: str) -> str:
    kind = block.get("kind")
    if kind == "heading":
        return "heading"
    if kind in {"table", "table_header", "table_row"}:
        return str(kind)
    if kind == "list_item":
        return "list_item"
    if extract_clause_marker(text):
        return "clause"
    if text.endswith(":"):
        return "lead_in"
    if is_signature_text(text):
        return "signature"
    return "paragraph"


def semantic_parent_block_id(
    *,
    block_type: str,
    clause_marker: str | None,
    current_lead_in_id: str | None,
) -> str | None:
    if block_type == "clause" and clause_marker:
        return current_lead_in_id
    if block_type == "list_item":
        return current_lead_in_id
    return None


def heading_level(text: str, section_count: int) -> int:
    if section_count == 0:
        return 1
    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S+", text):
        return 2
    if re.match(r"^[A-Z][.)]\s+\S+", text):
        return 3
    return 2


def extract_clause_marker(text: str) -> str | None:
    match = re.match(r"^\s*((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)])\s+", text)
    if not match:
        match = re.match(r"^\s*(\((?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\))\s+", text)
    return match.group(1) if match else None


def is_signature_text(text: str) -> bool:
    return text in {"For and on behalf of", "Name Name", "Date Date"} or text.startswith(
        "For and on behalf of "
    )


def append_section_text(existing: str, text: str, block_type: str) -> str:
    prefix = "- " if block_type == "list_item" else ""
    rendered = prefix + text
    return rendered if not existing else f"{existing}\n\n{rendered}"


def build_inlines_for_block(
    block_id: str,
    text: str,
    block_type: str,
    clause_marker: str | None,
    seen_inline_ids: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    if block_type == "heading":
        inline_id = unique_inline_id(text, seen_inline_ids)
        return [
            {
                "inline_id": inline_id,
                "block_id": block_id,
                "type": "heading_text",
                "text": text,
                "char_start": 0,
                "char_end": len(text),
            }
        ]
    content_start = len(clause_marker) + 1 if clause_marker else 0
    content = text[content_start:].strip()
    if not content:
        content = text
        content_start = 0
    segments = split_inline_segments(content)
    inlines: list[dict[str, Any]] = []
    cursor = content_start
    for index, segment in enumerate(segments, start=1):
        start = text.find(segment, cursor)
        if start < 0:
            start = cursor
        end = start + len(segment)
        inlines.append(
            {
                "inline_id": unique_inline_id(segment, seen_inline_ids),
                "block_id": block_id,
                "type": inline_type(segment, block_type, index),
                "text": segment,
                "char_start": start,
                "char_end": end,
            }
        )
        cursor = end
    return inlines


def extract_inline_id(text: str) -> str:
    normalized = normalize_inline_space(text)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"inline_{digest}"


def unique_inline_id(text: str, seen_inline_ids: dict[str, int] | None) -> str:
    inline_id = extract_inline_id(text)
    if seen_inline_ids is None:
        return inline_id
    count = seen_inline_ids.get(inline_id, 0) + 1
    seen_inline_ids[inline_id] = count
    if count == 1:
        return inline_id
    return f"{inline_id}_{count:03d}"


def split_inline_segments(text: str) -> list[str]:
    normalized = text.strip().rstrip(".;")
    if not normalized:
        return []
    parts = re.split(r";\s+", normalized)
    return [part.strip().rstrip(".;") for part in parts if part.strip()]


def inline_type(segment: str, block_type: str, index: int) -> str:
    lowered = segment.lower()
    if lowered.startswith(
        ("provided that", "except that", "unless ", "if ", "when ", "without ")
    ):
        return "condition"
    if re.match(r"^[\"“].+?[\"”]\s+shall mean\b", segment):
        return "definition"
    if block_type == "clause":
        return "clause_body" if index == 1 else "condition"
    if block_type == "lead_in":
        return "lead_in"
    return "sentence"


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
