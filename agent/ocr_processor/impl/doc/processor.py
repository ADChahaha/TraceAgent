from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

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
        warnings: list[str] = []
        try:
            conversion_result = docling_adapter.convert_with_docling(content, safe_filename)
            blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)
            engine = "docling"
        except Exception as exc:
            blocks = self._build_docx_blocks_from_zip(content)
            engine = "zip_xml_fallback"
            warnings.extend(
                [
                    "Docling DOCX pipeline failed; used zip/xml fallback.",
                    str(exc),
                ]
            )

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
                "engine": engine,
            },
            warnings=warnings,
        )

    def _resolve_doc_type(self, filename: str | None) -> FileType:
        if filename and filename.lower().endswith(".docx"):
            return FileType.DOCX
        return FileType.DOC

    def _build_docx_blocks_from_zip(self, content: bytes) -> list[ContentBlock]:
        xml_paths: list[str] = ["word/document.xml"]
        try:
            with ZipFile(BytesIO(content)) as archive:
                xml_paths.extend(
                    sorted(
                        name
                        for name in archive.namelist()
                        if name.startswith("word/header") or name.startswith("word/footer")
                    )
                )

                paragraphs: list[str] = []
                for xml_path in xml_paths:
                    if xml_path not in archive.namelist():
                        continue
                    paragraphs.extend(self._extract_paragraphs_from_docx_xml(archive.read(xml_path)))
        except BadZipFile:
            return []

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

    def _extract_paragraphs_from_docx_xml(self, xml_bytes: bytes) -> list[str]:
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return []

        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", namespace):
            text_parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
            text = " ".join("".join(text_parts).split()).strip()
            if text:
                paragraphs.append(text)

        return paragraphs
