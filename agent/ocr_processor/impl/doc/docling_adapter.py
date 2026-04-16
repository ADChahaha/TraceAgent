from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from io import BytesIO
from typing import Any

from ocr_processor.impl.docling_blocks import build_blocks_from_docling_document
from ocr_processor.schemas import ContentBlock


def convert_with_docling(content: bytes, filename: str) -> Any:
    document_stream_cls, _ = _load_docling_modules()
    converter = _get_default_converter()
    return converter.convert(document_stream_cls(name=filename, stream=BytesIO(content)))


@lru_cache(maxsize=1)
def _get_default_converter():
    _, document_converter_cls = _load_docling_modules()
    return document_converter_cls()


def build_blocks_from_docling_result(conversion_result: Any) -> list[ContentBlock]:
    return build_blocks_from_docling_document(conversion_result.document)


@lru_cache(maxsize=1)
def _load_docling_modules():
    base_models_module = import_module("docling.datamodel.base_models")
    document_converter_module = import_module("docling.document_converter")
    return (
        getattr(base_models_module, "DocumentStream"),
        getattr(document_converter_module, "DocumentConverter"),
    )
