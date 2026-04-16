from __future__ import annotations

from ..base import Processor
from ...schemas import ProcessResult
from ...types import FileType


class PdfProcessor(Processor):
    file_type = FileType.PDF

    def _process_content(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        return ProcessResult(
            processor_name="pdf_processor",
            file_type=self.file_type,
            filename=filename,
            blocks=[],
            meta_info={
                "byte_size": len(content),
                "source": "pdf",
            },
            warnings=["PDF processing logic has not been implemented yet."],
        )
