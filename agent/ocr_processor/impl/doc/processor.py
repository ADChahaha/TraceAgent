from __future__ import annotations

from ..base import Processor
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
        return ProcessResult(
            processor_name="doc_processor",
            file_type=resolved_type,
            filename=filename,
            blocks=[],
            meta_info={
                "byte_size": len(content),
                "source": resolved_type.value,
            },
            warnings=["DOC/DOCX processing logic has not been implemented yet."],
        )

    def _resolve_doc_type(self, filename: str | None) -> FileType:
        if filename and filename.lower().endswith(".docx"):
            return FileType.DOCX
        return FileType.DOC
