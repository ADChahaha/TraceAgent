from __future__ import annotations

from ..base import Processor
from .. import docling_adapter
from ...schemas import BoundingBox, ContentBlock, ProcessResult
from ...types import FileType
import pdfplumber
from io import BytesIO


class PdfProcessor(Processor):
    file_type = FileType.PDF

    def _process_content(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        safe_filename = filename or "document.pdf"
        try:
            conversion_result = docling_adapter.convert_with_docling(content, safe_filename)
            blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)
            warnings: list[str] = []
            if not blocks:
                warnings.append("No text blocks were extracted from the PDF.")
            return ProcessResult(
                processor_name="pdf_processor",
                file_type=self.file_type,
                filename=filename,
                blocks=blocks,
                meta_info={
                    "byte_size": len(content),
                    "source": "pdf",
                    "block_count": len(blocks),
                    "engine": "docling",
                },
                warnings=warnings,
            )
        except Exception as exc:
            return self._process_with_pdfplumber(
                content=content,
                filename=filename,
                fallback_reason=str(exc),
            )

    def _process_with_pdfplumber(
        self,
        *,
        content: bytes,
        filename: str | None,
        fallback_reason: str,
    ) -> ProcessResult:
        blocks: list[ContentBlock] = []
        warnings: list[str] = [
            "Docling PDF pipeline was unavailable in the current environment; used pdfplumber fallback.",
            fallback_reason,
        ]

        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(use_text_flow=True)
                for line_words in self._group_words_into_lines(words):
                    text = " ".join(word["text"] for word in line_words).strip()
                    if not text:
                        continue

                    blocks.append(
                        ContentBlock(
                            text=text,
                            page_no=page_number,
                            bbox=self._build_bbox(line_words),
                            kind="text",
                            meta_info={
                                "word_count": len(line_words),
                            },
                        )
                    )

        if not blocks:
            warnings.append("No text blocks were extracted from the PDF.")

        return ProcessResult(
            processor_name="pdf_processor",
            file_type=self.file_type,
            filename=filename,
            blocks=blocks,
            meta_info={
                "byte_size": len(content),
                "source": "pdf",
                "block_count": len(blocks),
                "engine": "pdfplumber_fallback",
            },
            warnings=warnings,
        )

    def _group_words_into_lines(
        self,
        words: list[dict],
        tolerance: float = 3.0,
    ) -> list[list[dict]]:
        if not words:
            return []

        ordered_words = sorted(words, key=lambda word: (float(word["top"]), float(word["x0"])))
        lines: list[dict[str, object]] = []

        for word in ordered_words:
            top = float(word["top"])
            if not lines or abs(top - float(lines[-1]["top"])) > tolerance:
                lines.append({"top": top, "words": [word]})
            else:
                lines[-1]["words"].append(word)

        return [line["words"] for line in lines]

    def _build_bbox(self, words: list[dict]) -> BoundingBox:
        x0 = min(float(word["x0"]) for word in words)
        y0 = min(float(word["top"]) for word in words)
        x1 = max(float(word["x1"]) for word in words)
        y1 = max(float(word["bottom"]) for word in words)
        return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
