"""Convert MinerU content_list_v2 pages to a traceable HTML document.

`build_html_from_content_list` 产出带 CSS 的完整 HTML 文档：前端 review /
iframe 直接渲染，同时保留 h1-h6 / p / ul / ol / table 结构骨架，供
file_extraction_agent 解析建树。
"""

from __future__ import annotations

import html
import json
import re
from typing import Any


def build_html_from_content_list(pages: list[list[dict[str, Any]]]) -> str:
    """Build a self-contained display HTML document from MinerU pages.

    产出带 CSS 的完整 HTML 文档：前端 review / iframe 直接渲染，同时保留
    h1-h6 / p / ul / ol / table 结构骨架，供 file_extraction_agent 解析建树。
    """

    fragment = "\n".join(
        rendered
        for page_idx in range(len(pages))
        if (rendered := render_page_from_markdown_blocks(classify_markdown_blocks(markdown_blocks(pages)), page_idx))
    )
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
{fragment}
</main>
</body>
</html>
"""


def markdown_blocks(
    pages: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten rendered MinerU blocks with layout features for markdown rules."""

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
    """Classify renderable blocks once so HTML and Markdown share structure.

    不再做聚类选 h2；只保留目录页识别和正文小标题降级两类轻量过滤。
    真正的大章节标题直接信任 MinerU 的 content.level。
    """

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


def markdown_block_from_source(
    block: dict[str, Any],
    page_no: int,
    block_idx: int,
) -> dict[str, Any]:
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
    if not text:
        return False
    if text in {"目次", "募集要項"}:
        return False
    if re.match(r"^<<.+>>$", text):
        return True
    if re.match(r"^【.+】$", text):
        return True
    if re.match(r"^[（(][0-9０-９一二三四五六七八九十A-Za-z]+[)）]\s*", text):
        return True
    if re.match(r"^[0-9０-９]+[）)]\s*", text):
        return True
    if re.match(r"^[A-Z]$", text):
        return True
    if re.match(r"^[a-z]$", text):
        return True
    source = block["block"]
    source_level = int(source.get("content", {}).get("level") or 0)
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


def render_page_from_markdown_blocks(
    blocks: list[dict[str, Any]], page_idx: int
) -> str:
    rendered = render_blocks_with_sections(
        [block for block in blocks if block["page_no"] == page_idx + 1],
        page_idx,
    )
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
    for markdown_block in blocks:
        block_id = f"p{page_idx + 1:03d}_b{markdown_block['block_idx']:03d}"
        heading_level = markdown_heading_level(markdown_block)
        if heading_level == 2:
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
        elif heading_level == 3:
            if open_subsection:
                rendered.append("</section>")
            rendered.append(
                f'<section class="subsection subsection-level-3" id="{block_id}_subsection" '
                f'data-section-level="3" data-page="{page_idx + 1}" '
                f'aria-labelledby="{block_id}">'
            )
            open_subsection = True
        rendered.append(render_markdown_block(markdown_block, page_idx))
    if open_subsection:
        rendered.append("</section>")
    if open_section:
        rendered.append("</section>")
    return rendered


def render_markdown_block(markdown_block: dict[str, Any], page_idx: int) -> str:
    return render_block(
        markdown_block["block"],
        page_idx,
        int(markdown_block["block_idx"]),
        markdown_block=markdown_block,
    )


def render_block(
    block: dict[str, Any],
    page_idx: int,
    block_idx: int,
    *,
    markdown_block: dict[str, Any] | None = None,
) -> str:
    block_id = f"p{page_idx + 1:03d}_b{block_idx:03d}"
    block_type = block.get("type", "unknown")
    content = block.get("content", {})
    attrs = block_attrs(block_id, page_idx, block)

    if block_type == "title":
        if markdown_block is None:
            markdown_block = classify_markdown_blocks(
                [markdown_block_from_source(block, page_idx + 1, block_idx)]
            )[0]
        level = markdown_heading_level(markdown_block)
        text = flatten_text(content.get("title_content"))
        if level is None:
            return f"<p {attrs}>{html.escape(text)}</p>"
        level = max(1, min(level, 6))
        if level >= 4:
            return f"<p {attrs}>{html.escape(text)}</p>"
        return f"<h{level} {attrs}>{html.escape(text)}</h{level}>"

    if block_type == "paragraph":
        text = flatten_text(content.get("paragraph_content"))
        if markdown_is_body_subheading(markdown_block_from_source(block, page_idx + 1, block_idx)):
            return f"<p {attrs}>{html.escape(text)}</p>"
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


def normalize_inline_space(text: str) -> str:
    return " ".join(text.split())


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
