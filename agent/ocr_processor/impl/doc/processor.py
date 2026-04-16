from __future__ import annotations

from ..base import Processor
from .. import docling_adapter
from ...schemas import ProcessResult
from ...types import FileType


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
                processor_name="doc_processor",
                file_type=resolved_type,
                filename=filename,
                blocks=[],
                meta_info={
                    "byte_size": len(content),
                    "source": resolved_type.value,
                    "block_count": 0,
                    "engine": "unimplemented",
                },
                warnings=["Legacy .doc processing is not implemented yet."],
            )

        safe_filename = filename or "document.docx"
        conversion_result = docling_adapter.convert_with_docling(content, safe_filename)
        blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)
        warnings: list[str] = []
        if not blocks:
            warnings.append("No text blocks were extracted from the DOCX file.")

        return ProcessResult(
            processor_name="doc_processor",
            file_type=resolved_type,
            filename=filename,
            blocks=blocks,
            meta_info={
                "byte_size": len(content),
                "source": resolved_type.value,
                "block_count": len(blocks),
                "engine": "docling",
            },
            warnings=warnings,
        )

    def _resolve_doc_type(self, filename: str | None) -> FileType:
        if filename and filename.lower().endswith(".docx"):
            return FileType.DOCX
        return FileType.DOC
