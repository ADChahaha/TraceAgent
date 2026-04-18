from __future__ import annotations

from document_processor.impl.base import Processor
from document_processor.impl.doc import docling_adapter
from document_processor.impl.markdown_export import (
    build_markdown_items_from_blocks,
    build_meta_info_from_blocks,
)
from document_processor.schemas import ProcessResult
from document_processor.types import FileType


class DocProcessor(Processor):
    file_type = FileType.DOC

    def __init__(self, resolved_type: FileType | None = None):
        self._resolved_type = resolved_type

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
                md_list=[],
                markdown="",
                blocks=[],
                meta_info=build_meta_info_from_blocks(
                    [],
                    engine="unsupported_doc",
                    fallback_used=False,
                ),
                warnings=["Legacy .doc processing is not implemented yet."],
            )

        safe_filename = filename or "document.docx"
        conversion_result = docling_adapter.convert_with_docling(content, safe_filename)
        blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)
        if not blocks:
            raise RuntimeError("Docling DOCX pipeline returned no text blocks.")

        md_list = build_markdown_items_from_blocks(blocks)
        return ProcessResult(
            file_type=resolved_type,
            filename=filename,
            md_list=md_list,
            markdown="\n\n".join(item for item in md_list if item).strip(),
            blocks=blocks,
            meta_info=build_meta_info_from_blocks(
                blocks,
                engine="docling",
                fallback_used=False,
            ),
            warnings=[],
        )

    def _resolve_doc_type(self, filename: str | None) -> FileType:
        if self._resolved_type is not None:
            return self._resolved_type
        if filename and filename.lower().endswith(".docx"):
            return FileType.DOCX
        return FileType.DOC
