from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..base import Processor
from .. import docling_adapter
from ...schemas import ContentBlock, ProcessResult
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
            return self._process_legacy_doc(content=content, filename=filename)

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

    def _process_legacy_doc(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> ProcessResult:
        try:
            extracted_text = self._extract_legacy_doc_text(content=content, filename=filename)
        except RuntimeError as exc:
            return ProcessResult(
                processor_name="doc_processor",
                file_type=FileType.DOC,
                filename=filename,
                blocks=[],
                meta_info={
                    "byte_size": len(content),
                    "source": FileType.DOC.value,
                    "block_count": 0,
                    "engine": "textutil_unavailable",
                },
                warnings=[str(exc)],
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "No error details were returned."
            return ProcessResult(
                processor_name="doc_processor",
                file_type=FileType.DOC,
                filename=filename,
                blocks=[],
                meta_info={
                    "byte_size": len(content),
                    "source": FileType.DOC.value,
                    "block_count": 0,
                    "engine": "textutil_failed",
                },
                warnings=[f"textutil failed to extract legacy .doc content: {stderr}"],
            )

        blocks = self._build_text_blocks(extracted_text)
        warnings: list[str] = []
        if not blocks:
            warnings.append("No text blocks were extracted from the legacy DOC file.")

        return ProcessResult(
            processor_name="doc_processor",
            file_type=FileType.DOC,
            filename=filename,
            blocks=blocks,
            meta_info={
                "byte_size": len(content),
                "source": FileType.DOC.value,
                "block_count": len(blocks),
                "engine": "textutil",
            },
            warnings=warnings,
        )

    def _extract_legacy_doc_text(
        self,
        *,
        content: bytes,
        filename: str | None,
    ) -> str:
        textutil_path = shutil.which("textutil")
        if textutil_path is None:
            raise RuntimeError("Legacy .doc extraction requires `textutil`, but it is not available.")

        safe_filename = Path(filename or "document.doc").name
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_path = Path(tmpdir) / safe_filename
            doc_path.write_bytes(content)

            completed = subprocess.run(
                [
                    textutil_path,
                    "-convert",
                    "txt",
                    "-stdout",
                    "-encoding",
                    "UTF-8",
                    str(doc_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return completed.stdout

    def _build_text_blocks(self, extracted_text: str) -> list[ContentBlock]:
        normalized_text = extracted_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized_text:
            return []

        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n", normalized_text)
            if paragraph.strip()
        ]
        if not paragraphs:
            paragraphs = [
                re.sub(r"\s+", " ", line).strip()
                for line in normalized_text.splitlines()
                if line.strip()
            ]

        return [
            ContentBlock(
                text=paragraph,
                page_no=None,
                bbox=None,
                kind="text",
                meta_info={},
            )
            for paragraph in paragraphs
        ]
