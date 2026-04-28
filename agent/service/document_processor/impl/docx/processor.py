"""基于 python-docx 的 DOCX 处理器。

实现步骤：

```text
调用方把 docx file_obj 交给 DocxProcessor.process(...)
  -> 基类先校验 file_obj 至少提供可调用的 read()
  -> DocxProcessor 读取二进制内容，并从 filename/name 推出输出文件名
  -> 用 python-docx 的 Document(BytesIO(...)) 直接打开文档
  -> 按 body 中的真实顺序遍历 paragraph/table
  -> heading 段落转成标题 markdown，普通段落转成正文 markdown，表格转成简单 markdown table
  -> 同时把每个正文单元归一化成 ContentBlock
  -> 返回统一的 ProcessResult(file_type/markdown/md_list/blocks/meta_info)
```
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from service.document_processor.impl.base import BaseDocumentProcessor
from service.document_processor.schemas import ContentBlock, ProcessResult
from service.document_processor.types import FileType


class DocxProcessor(BaseDocumentProcessor):
    """使用 python-docx 解析 DOCX 的具体处理器。"""

    file_type = FileType.DOCX

    def _process(self, file_obj):
        filename = self._resolve_filename(file_obj)
        source_bytes = self._read_source_bytes(file_obj)
        document = Document(BytesIO(source_bytes))

        markdown_parts: list[str] = []
        blocks: list[ContentBlock] = []
        paragraph_count = 0
        table_count = 0

        for body_item in self._iter_body_items(document):
            if isinstance(body_item, Paragraph):
                paragraph_count += 1
                markdown_part, paragraph_blocks = self._convert_paragraph(body_item)
            else:
                table_count += 1
                markdown_part, paragraph_blocks = self._convert_table(body_item)

            if markdown_part:
                markdown_parts.append(markdown_part)
            blocks.extend(paragraph_blocks)

        markdown = "\n\n".join(part for part in markdown_parts if part)

        return ProcessResult(
            file_type=self.file_type.value,
            filename=filename,
            md_list=[markdown] if markdown else [],
            markdown=markdown,
            blocks=blocks,
            meta_info={
                "paragraph_count": paragraph_count,
                "table_count": table_count,
            },
        )

    @staticmethod
    def _resolve_filename(file_obj) -> str:
        filename = getattr(file_obj, "filename", None) or getattr(file_obj, "name", None)
        if filename:
            return Path(str(filename)).name
        return "document.docx"

    @staticmethod
    def _read_source_bytes(file_obj) -> bytes:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        source_bytes = file_obj.read()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return source_bytes

    @staticmethod
    def _iter_body_items(document):
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                yield Paragraph(child, document)
            elif child.tag.endswith("}tbl"):
                yield Table(child, document)

    @classmethod
    def _convert_paragraph(cls, paragraph: Paragraph) -> tuple[str, list[ContentBlock]]:
        text = cls._normalize_text(paragraph.text)
        if not text:
            return "", []

        style_name = paragraph.style.name if paragraph.style is not None else ""
        heading_level = cls._infer_heading_level(style_name)
        if heading_level is not None:
            markdown = f"{'#' * heading_level} {text}"
            kind = "section_header"
        else:
            markdown = text
            kind = "text"

        return markdown, [
            ContentBlock(
                text=text,
                kind=kind,
                meta_info={
                    "style_name": style_name,
                },
            )
        ]

    @classmethod
    def _convert_table(cls, table: Table) -> tuple[str, list[ContentBlock]]:
        rows = []
        blocks: list[ContentBlock] = []

        for row in table.rows:
            cells = [cls._normalize_text(cell.text) for cell in row.cells]
            rows.append(cells)
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                blocks.append(
                    ContentBlock(
                        text=row_text,
                        kind="table",
                    )
                )

        markdown = cls._table_to_markdown(rows)
        return markdown, blocks

    @staticmethod
    def _infer_heading_level(style_name: str) -> int | None:
        if not style_name:
            return None

        normalized = style_name.lower()
        if normalized == "title":
            return 1
        if normalized.startswith("heading "):
            suffix = normalized.removeprefix("heading ").strip()
            if suffix.isdigit():
                return max(1, min(int(suffix), 6))
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.split())

    @classmethod
    def _table_to_markdown(cls, rows: list[list[str]]) -> str:
        if not rows:
            return ""

        column_count = max(len(row) for row in rows)
        normalized_rows = [
            row + [""] * (column_count - len(row))
            for row in rows
        ]
        header = normalized_rows[0]
        separator = ["---"] * column_count
        markdown_rows = [header, separator, *normalized_rows[1:]]

        return "\n".join(
            "| " + " | ".join(cell or " " for cell in row) + " |"
            for row in markdown_rows
        )
