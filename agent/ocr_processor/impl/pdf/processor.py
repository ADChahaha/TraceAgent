from __future__ import annotations

from ocr_processor.impl.base import Processor
from ocr_processor.impl.pdf import docling_adapter
from ocr_processor.impl.markdown_export import (
    build_markdown_items_from_blocks,
    build_meta_info_from_blocks,
)
from ocr_processor.schemas import ProcessResult
from ocr_processor.types import FileType


class PdfProcessor(Processor):
    file_type = FileType.PDF

    def _process_content(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        safe_filename = filename or "document.pdf"
        conversion_result = docling_adapter.convert_pdf_with_docling(content, safe_filename)
        blocks = docling_adapter.build_blocks_from_docling_result(
            conversion_result,
            pdf_bytes=content,
        )
        if not blocks:
            raise RuntimeError("Docling PDF pipeline returned no text blocks.")

        md_list = build_markdown_items_from_blocks(blocks)
        return ProcessResult(
            file_type=self.file_type,
            filename=filename,
            md_list=md_list,
            markdown="\n\n".join(item for item in md_list if item).strip(),
            blocks=blocks,
            meta_info=build_meta_info_from_blocks(
                blocks,
                engine="docling_rapidocr",
                fallback_used=False,
            ),
            warnings=[],
        )
