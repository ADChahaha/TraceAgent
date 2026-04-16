from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import Any

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

from ocr_processor.docling_blocks import build_blocks_from_docling_document
from ocr_processor.schemas import ContentBlock


def convert_with_docling(content: bytes, filename: str) -> Any:
    converter = _get_default_converter()
    return converter.convert(DocumentStream(name=filename, stream=BytesIO(content)))


@lru_cache(maxsize=1)
def _get_default_converter() -> DocumentConverter:
    return DocumentConverter()


def build_blocks_from_docling_result(conversion_result: Any) -> list[ContentBlock]:
    return build_blocks_from_docling_document(conversion_result.document)
