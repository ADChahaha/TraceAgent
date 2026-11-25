"""Convert MinerU content_list_v2 pages to a traceable HTML document.

`build_html_from_content_list` 产出带 CSS 的完整 HTML 文档，同时保留
h1-h6 / p / ul / ol / table 结构骨架，供后续文档树物化使用。
"""

from __future__ import annotations

import html
import json
from typing import Any

from document_service.document_processor.pdf.html_blocks import (
    block_text,
    classify_markdown_blocks,
    detect_table_of_contents_pages,
    flatten_text,
    infer_markdown_heading_level,
    is_table_of_contents_heading,
    markdown_block_from_source,
    markdown_blocks,
    markdown_heading_level,
    markdown_is_body_subheading,
    markdown_layout_features,
    markdown_title_level,
    normalize_inline_space,
    normalize_table_of_contents_text,
    should_render_block,
    table_text,
)
from document_service.document_processor.pdf.html_tables import (
    ensure_table_caption,
    ensure_table_evidence_ids,
    ensure_table_root,
    extract_table_row_texts,
    extract_table_rows,
    extract_text_from_table_html,
    render_table as _render_table_impl,
    strip_html_tags,
)


def build_html_from_content_list(pages: list[list[dict[str, Any]]]) -> str:
    """将 MinerU pages 构建为自包含可追溯 HTML 文档。"""
    classified = classify_markdown_blocks(markdown_blocks(pages))
    fragment = "\n".join(
        rendered
        for page_idx in range(len(pages))
        if (rendered := render_page_from_markdown_blocks(classified, page_idx))
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


def render_page_from_markdown_blocks(blocks: list[dict[str, Any]], page_idx: int) -> str:
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
        if level is None or level >= 4:
            return f"<p {attrs}>{html.escape(text)}</p>"
        level = max(1, min(level, 6))
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
    return _render_table_impl(block, block_id, page_idx, attrs, flatten_text=flatten_text)


def render_list_items(items: list[dict[str, Any]], page_idx: int, block_id: str, attrs: str) -> str:
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


__all__ = [
    "block_attrs",
    "block_text",
    "build_html_from_content_list",
    "classify_markdown_blocks",
    "detect_table_of_contents_pages",
    "ensure_table_caption",
    "ensure_table_evidence_ids",
    "ensure_table_root",
    "extract_table_row_texts",
    "extract_table_rows",
    "extract_text_from_table_html",
    "flatten_text",
    "infer_markdown_heading_level",
    "is_table_of_contents_heading",
    "markdown_block_from_source",
    "markdown_blocks",
    "markdown_heading_level",
    "markdown_is_body_subheading",
    "markdown_layout_features",
    "markdown_title_level",
    "normalize_inline_space",
    "normalize_table_of_contents_text",
    "render_block",
    "render_blocks_with_sections",
    "render_list_items",
    "render_markdown_block",
    "render_page_from_markdown_blocks",
    "render_table",
    "should_render_block",
    "strip_html_tags",
    "table_text",
]
