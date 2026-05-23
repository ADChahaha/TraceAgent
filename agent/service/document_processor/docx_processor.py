"""DOCX 文件对象到 traceable HTML 的 pipeline 入口。

实现步骤：

```text
调用方传入 .docx file_obj
  -> validate_file_obj(file_obj) 检查 read() 是否可调用
  -> resolve_docx_filename(file_obj) 从 filename/name 取源文件基名，没有则用 document.docx
  -> read_source_bytes(file_obj) 读取 DOCX 二进制并尽量复位文件指针
  -> python-docx Document(BytesIO(source_bytes)) 打开 Word 文档
  -> iter_block_items(document) 按 body 原始顺序遍历 paragraph/table
  -> Word heading style 创建 section stack；普通段落和表格不猜标题
  -> 生成 html/display_html/markdown/md_list/blocks/semantic_document
  -> ProcessResult(filename, html, ...)
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from service.document_processor.processor import read_source_bytes, validate_file_obj
from service.document_processor.schemas import ProcessResult


@dataclass(slots=True)
class _DocxBlock:
    block_id: str
    kind: str
    text: str
    style_name: str | None = None
    level: int | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _DocxSection:
    section_id: str
    title: str
    level: int
    block_ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def process_docx(file_obj) -> ProcessResult:
    """把一个 DOCX 文件对象转换成抽取友好的 HTML。"""

    validate_file_obj(file_obj)
    filename = resolve_docx_filename(file_obj)
    source_bytes = read_source_bytes(file_obj)
    document = Document(BytesIO(source_bytes))
    blocks, sections = build_docx_blocks(document)
    html = build_html(blocks)
    return ProcessResult(
        filename=filename,
        html=html,
        display_html=build_display_html(html),
        markdown=build_markdown(blocks),
        md_list=[block.text for block in blocks if block.text],
        blocks=[process_block_to_dict(block) for block in blocks],
        semantic_document=build_semantic_document(blocks, sections),
        meta_info={"engine": "python-docx"},
        warnings=[],
    )


def resolve_docx_filename(file_obj) -> str:
    """从上传对象里取源文件名，缺省时回退为 document.docx。"""

    for attr_name in ("filename", "name"):
        value = getattr(file_obj, attr_name, None)
        if isinstance(value, str) and value.strip():
            return Path(value).name
    return "document.docx"


def build_docx_blocks(document: DocxDocument) -> tuple[list[_DocxBlock], list[_DocxSection]]:
    blocks: list[_DocxBlock] = []
    sections: list[_DocxSection] = []
    section_stack: list[_DocxSection] = []

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
                while section_stack and section_stack[-1].level >= heading_level:
                    section_stack.pop()
                section = _DocxSection(
                    section_id=block_id,
                    title=text,
                    level=heading_level,
                )
                sections.append(section)
                section_stack.append(section)
                append_block_to_sections(section_stack, block)
                continue

            block = _DocxBlock(
                block_id=block_id,
                kind="paragraph",
                text=text,
                style_name=style_name,
            )
            blocks.append(block)
            append_block_to_sections(section_stack, block)
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
            append_block_to_sections(section_stack, block)

    return blocks, sections


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


def append_block_to_sections(section_stack: list[_DocxSection], block: _DocxBlock) -> None:
    for section in section_stack:
        section.block_ids.append(block.block_id)
        section.texts.append(block.text)


def process_block_to_dict(block: _DocxBlock) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "block_id": block.block_id,
        "text": block.text,
        "page_no": None,
        "bbox": None,
        "kind": block.kind,
        "meta_info": {"source": "docx"},
    }
    if block.style_name:
        payload["meta_info"]["style"] = block.style_name
    if block.level is not None:
        payload["meta_info"]["level"] = block.level
    if block.rows:
        payload["rows"] = block.rows
    return payload


def build_semantic_document(
    blocks: list[_DocxBlock],
    sections: list[_DocxSection],
) -> dict[str, Any]:
    return {
        "sections": [
            {
                "section_id": section.section_id,
                "title": section.title,
                "level": section.level,
                "text": "\n".join(section.texts),
                "block_ids": section.block_ids,
            }
            for section in sections
        ],
        "blocks": [
            {
                **process_block_to_dict(block),
                "type": block.kind,
            }
            for block in blocks
        ],
        "inlines": [],
    }


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


def build_markdown(blocks: list[_DocxBlock]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            level = block.level or 1
            lines.append(f"{'#' * level} {block.text}")
        elif block.kind == "table":
            lines.extend(table_markdown_lines(block))
        else:
            lines.append(block.text)
        lines.append("")
    return "\n".join(lines).strip()


def table_markdown_lines(block: _DocxBlock) -> list[str]:
    if not block.rows:
        return []
    lines = [markdown_row(block.rows[0]["cells"])]
    lines.append(markdown_row(["---" for _ in block.rows[0]["cells"]]))
    for row in block.rows[1:]:
        lines.append(markdown_row(row["cells"]))
    return lines


def markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def normalize_text(text: str) -> str:
    return " ".join(str(text).split())
