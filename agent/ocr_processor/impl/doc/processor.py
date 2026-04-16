from __future__ import annotations

import re
from io import BytesIO

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from ocr_processor.impl.base import Processor
from ocr_processor.impl.doc import docling_adapter
from ocr_processor.markdown_export import build_markdown_from_blocks
from ocr_processor.schemas import ContentBlock, ProcessResult
from ocr_processor.types import FileType


class DocProcessor(Processor):
    file_type = FileType.DOC

    def _process_content(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        resolved_type = self._resolve_doc_type(filename)
        if resolved_type == FileType.DOC:
            return ProcessResult(
                file_type=resolved_type,
                filename=filename,
                markdown="",
                blocks=[],
                warnings=["Legacy .doc processing is not implemented yet."],
            )

        safe_filename = filename or "document.docx"
        warnings: list[str] = []
        try:
            conversion_result = docling_adapter.convert_with_docling(content, safe_filename)
            blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)
            if not blocks:
                blocks = self._build_docx_blocks_from_python_docx(content)
                warnings.append(
                    "Docling DOCX pipeline returned no blocks; used python-docx fallback."
                )
        except Exception as exc:
            blocks = self._build_docx_blocks_from_python_docx(content)
            warnings.extend(
                [
                    "Docling DOCX pipeline failed; used python-docx fallback.",
                    str(exc),
                ]
            )

        if not blocks:
            warnings.append("No text blocks were extracted from the DOCX file.")

        return ProcessResult(
            file_type=resolved_type,
            filename=filename,
            markdown=build_markdown_from_blocks(blocks),
            blocks=blocks,
            warnings=warnings,
        )

    def _resolve_doc_type(self, filename: str | None) -> FileType:
        if filename and filename.lower().endswith(".docx"):
            return FileType.DOCX
        return FileType.DOC

    def _build_docx_blocks_from_python_docx(self, content: bytes) -> list[ContentBlock]:
        try:
            document = Document(BytesIO(content))
        except Exception:
            return []

        elements = list(self._iter_document_blocks(document))
        blocks: list[ContentBlock] = []
        for index, element in enumerate(elements):
            if isinstance(element, Paragraph):
                content_block = self._build_content_block_from_paragraph(
                    element,
                    elements=elements,
                    index=index,
                )
            elif isinstance(element, Table):
                content_block = self._build_content_block_from_table(element)
            else:
                content_block = None

            if content_block is None:
                continue

            blocks.append(content_block)

        return self._dedupe_adjacent_blocks(blocks)

    def _iter_document_blocks(self, document: DocumentObject):
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, document)
            elif isinstance(child, CT_Tbl):
                yield Table(child, document)

    def _build_content_block_from_paragraph(
        self,
        paragraph: Paragraph,
        *,
        elements: list[Paragraph | Table],
        index: int,
    ) -> ContentBlock | None:
        text = self._normalize_docx_text(paragraph.text)
        if not text:
            return None

        return ContentBlock(
            text=text,
            page_no=None,
            bbox=None,
            kind=self._classify_docx_paragraph_kind(
                paragraph,
                text=text,
                elements=elements,
                index=index,
            ),
            meta_info={},
        )

    def _build_content_block_from_table(self, table: Table) -> ContentBlock | None:
        rows: list[list[str]] = []
        for row in table.rows:
            normalized_row = [self._normalize_docx_text(cell.text) for cell in row.cells]
            if any(normalized_row):
                rows.append(normalized_row)

        if not rows:
            return None

        markdown = self._table_rows_to_markdown(rows)
        return ContentBlock(
            text=markdown,
            page_no=None,
            bbox=None,
            kind="table",
            meta_info={
                "row_count": len(rows),
                "column_count": max(len(row) for row in rows),
                "format": "markdown",
            },
        )

    def _classify_docx_paragraph_kind(
        self,
        paragraph: Paragraph,
        *,
        text: str,
        elements: list[Paragraph | Table],
        index: int,
    ) -> str:
        compact_text = re.sub(r"\s+", "", text)
        style_name = (paragraph.style.name if paragraph.style is not None else "").strip().lower()

        if self._is_explicit_heading_style(style_name):
            return "heading"

        if paragraph.alignment == WD_PARAGRAPH_ALIGNMENT.CENTER and self._looks_like_display_title(
            compact_text
        ):
            return "heading" if len(compact_text) <= 12 else "subheading"

        previous_is_blank = self._adjacent_paragraph_is_blank(elements, index=index, direction=-1)
        next_is_blank = self._adjacent_paragraph_is_blank(elements, index=index, direction=1)
        next_nonempty = self._find_next_nonempty_element(elements, index=index)
        if self._looks_like_standalone_heading(compact_text) and (
            previous_is_blank or next_is_blank or self._element_suggests_section_body(next_nonempty)
        ):
            return "heading"

        return "text"

    def _normalize_docx_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _table_rows_to_markdown(self, rows: list[list[str]]) -> str:
        column_count = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
        lines: list[str] = []

        header = normalized_rows[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in range(column_count)) + " |")

        for row in normalized_rows[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _dedupe_adjacent_blocks(self, blocks: list[ContentBlock]) -> list[ContentBlock]:
        deduped: list[ContentBlock] = []
        previous_signature: tuple[str, str] | None = None

        for block in blocks:
            signature = (block.kind, block.text)
            if signature == previous_signature:
                continue
            deduped.append(block)
            previous_signature = signature

        return deduped

    def _is_explicit_heading_style(self, style_name: str) -> bool:
        return any(keyword in style_name for keyword in ("heading", "title", "标题"))

    def _looks_like_display_title(self, compact_text: str) -> bool:
        if not compact_text or len(compact_text) > 30:
            return False
        if self._looks_like_date_text(compact_text) or self._looks_like_placeholder(compact_text):
            return False
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", compact_text))

    def _looks_like_standalone_heading(self, compact_text: str) -> bool:
        if not compact_text or len(compact_text) > 24:
            return False
        if self._looks_like_date_text(compact_text) or self._looks_like_placeholder(compact_text):
            return False
        if re.search(r"[。！？!?；;]$", compact_text):
            return False
        return bool(
            re.search(r"[\u4e00-\u9fffA-Za-z]", compact_text)
            or re.match(r"^(\d+|[一二三四五六七八九十]+)[.、)]", compact_text)
        )

    def _looks_like_date_text(self, compact_text: str) -> bool:
        return bool(re.fullmatch(r"[\d零一二三四五六七八九十年月日/\-.]+", compact_text))

    def _looks_like_placeholder(self, compact_text: str) -> bool:
        return bool(re.fullmatch(r"[xX_·.]{3,}", compact_text))

    def _adjacent_paragraph_is_blank(
        self,
        elements: list[Paragraph | Table],
        *,
        index: int,
        direction: int,
    ) -> bool:
        cursor = index + direction
        if cursor < 0 or cursor >= len(elements):
            return False

        neighbor = elements[cursor]
        if isinstance(neighbor, Table):
            return False

        return not self._normalize_docx_text(neighbor.text)

    def _find_next_nonempty_element(
        self,
        elements: list[Paragraph | Table],
        *,
        index: int,
    ) -> Paragraph | Table | None:
        for cursor in range(index + 1, len(elements)):
            candidate = elements[cursor]
            if isinstance(candidate, Table):
                return candidate
            if self._normalize_docx_text(candidate.text):
                return candidate
        return None

    def _element_suggests_section_body(self, element: Paragraph | Table | None) -> bool:
        if element is None:
            return False
        if isinstance(element, Table):
            return True

        next_text = re.sub(r"\s+", "", element.text)
        if not next_text:
            return False
        if len(next_text) > 24:
            return True
        if self._looks_like_placeholder(next_text):
            return True
        return bool(re.search(r"[，。,：:；;]", next_text))
