"""DOCX 二进制到可追溯 HTML 的解析，全部折在本模块。

对外只暴露一个函数 `convert_docx_to_html(source_bytes)`。解析细节：

```text
source_bytes
  -> python-docx Document(BytesIO(source_bytes)) 打开 Word 文档
  -> iter_block_items(...) 按 Word body 原始顺序遍历 paragraph/table
  -> 空 paragraph 跳过；Word heading style 生成 heading block，其余为 paragraph
  -> table 保留原顺序生成 table block
  -> build_html(...) 产出带 CSS 的完整 HTML 文档
  -> 返回 html 字符串
```

`convert_docx_to_html` 不做启发式标题识别：只有显式的 Word heading style
才会生成 heading block；没有 heading style 的文档保持 flat paragraph/table blocks。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

__all__ = ["convert_docx_to_html"]


def convert_docx_to_html(source_bytes: bytes) -> str:
    """DOCX bytes -> 带 CSS 的完整 HTML 文档。"""

    document = Document(BytesIO(source_bytes))
    blocks = build_docx_blocks(document)
    return build_display_html(build_html(blocks))


@dataclass(slots=True)
class _DocxBlock:
    block_id: str
    kind: str
    text: str
    style_name: str | None = None
    level: int | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)


def build_docx_blocks(document: DocxDocument) -> list[_DocxBlock]:
    blocks: list[_DocxBlock] = []

    for item in iter_block_items(document):
        block_id = f"docx_b{len(blocks) + 1:03d}"
        if isinstance(item, Paragraph):
            text = normalize_text(item.text)
            if not text:
                continue
            style_name = paragraph_style_name(item)
            heading_level = parse_heading_level(style_name)
            if heading_level is not None:
                block = _DocxBlock(
                    block_id=block_id,
                    kind="heading",
                    text=text,
                    style_name=style_name,
                    level=heading_level,
                )
                blocks.append(block)
                continue

            block = _DocxBlock(
                block_id=block_id,
                kind="paragraph",
                text=text,
                style_name=style_name,
            )
            blocks.append(block)
            continue

        if isinstance(item, Table):
            rows = table_rows(item, block_id)
            if not rows:
                continue
            block = _DocxBlock(
                block_id=block_id,
                kind="table",
                text=" ".join(row["text"] for row in rows),
                rows=rows,
            )
            blocks.append(block)

    return blocks


def iter_block_items(document: DocxDocument) -> Iterable[Paragraph | Table]:
    """按 Word body 的原始顺序产出段落和表格。"""

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def paragraph_style_name(paragraph: Paragraph) -> str:
    style = paragraph.style
    return str(getattr(style, "name", "") or "")


def parse_heading_level(style_name: str) -> int | None:
    """只从 Word heading style 识别标题层级，不看字号或粗体。"""

    normalized = style_name.strip()
    match = re.match(r"^(?:Heading|标题|見出し)\s+([1-9])$", normalized, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def table_rows(table: Table, block_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows, start=1):
        cells = [normalize_text(cell.text) for cell in row.cells]
        if not any(cells):
            continue
        row_id = f"{block_id}_tr_{row_index:03d}"
        rows.append(
            {
                "row_id": row_id,
                "cells": cells,
                "text": " ".join(cell for cell in cells if cell),
                "row_index": row_index,
            }
        )
    return rows


def build_html(blocks: list[_DocxBlock]) -> str:
    lines: list[str] = []
    open_section_levels: list[int] = []
    for block in blocks:
        if block.kind == "heading":
            level = block.level or 1
            while open_section_levels and open_section_levels[-1] >= level:
                lines.append("</section>")
                open_section_levels.pop()
            lines.append(
                f'<section id="{block.block_id}_section" class="docx-section section-level-{level}" '
                f'data-element-id="{block.block_id}_section" data-type="section" '
                f'aria-labelledby="{block.block_id}">'
            )
            open_section_levels.append(level)
            lines.append(
                f'<h{level} id="{block.block_id}" class="block block-heading" '
                f'data-element-id="{block.block_id}" data-type="heading" data-level="{level}">'
                f"{escape(block.text)}</h{level}>"
            )
        elif block.kind == "paragraph":
            lines.append(
                f'<p id="{block.block_id}" class="block block-paragraph" '
                f'data-element-id="{block.block_id}" data-type="paragraph">'
                f"{escape(block.text)}</p>"
            )
        elif block.kind == "table":
            lines.append(build_table_html(block))

    while open_section_levels:
        lines.append("</section>")
        open_section_levels.pop()
    return "\n".join(lines)


def build_table_html(block: _DocxBlock) -> str:
    lines = [
        f'<table id="{block.block_id}" class="block block-table" '
        f'data-element-id="{block.block_id}" data-type="table">'
    ]
    for row in block.rows:
        lines.append(
            f'<tr id="{row["row_id"]}" data-element-id="{row["row_id"]}" data-type="table_row">'
        )
        for cell in row["cells"]:
            lines.append(f"<td>{escape(cell)}</td>")
        lines.append("</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def build_display_html(fragment_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Processed DOCX</title>
<style>
body {{ margin: 0; background: #ffffff; color: #171717; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width: 900px; margin: 0 auto; padding: 28px 36px; }}
.block {{ scroll-margin: 80px; }}
h1, h2, h3, h4, h5, h6 {{ line-height: 1.35; margin: 18px 0 10px; }}
p {{ font-size: 14px; line-height: 1.75; margin: 8px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 13px; }}
td, th {{ border: 1px solid #737373; padding: 6px 8px; vertical-align: top; }}
.block:hover {{ outline: 2px solid #2563eb; outline-offset: 2px; }}
.dp-evidence-highlight {{ outline: 3px solid #f59e0b; background-color: #fff7cc; }}
</style>
</head>
<body>
<main>
{fragment_html}
</main>
</body>
</html>
"""


def normalize_text(text: str) -> str:
    return " ".join(str(text).split())
