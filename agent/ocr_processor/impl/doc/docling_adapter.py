from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import Any

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

from ocr_processor.schemas import ContentBlock


def convert_with_docling(content: bytes, filename: str) -> Any:
    converter = _get_default_converter()
    return converter.convert(DocumentStream(name=filename, stream=BytesIO(content)))


@lru_cache(maxsize=1)
def _get_default_converter() -> DocumentConverter:
    return DocumentConverter()


def build_blocks_from_docling_result(conversion_result: Any) -> list[ContentBlock]:
    document = conversion_result.document
    blocks: list[ContentBlock] = []

    for text_item in getattr(document, "texts", []):
        text = getattr(text_item, "text", "").strip()
        if not text:
            continue

        provenance = getattr(text_item, "prov", None) or []
        first_prov = provenance[0] if provenance else None
        block_meta: dict[str, Any] = {}
        if first_prov is not None:
            charspan = getattr(first_prov, "charspan", None)
            if charspan is not None:
                block_meta["charspan"] = list(charspan)

        blocks.append(
            ContentBlock(
                text=text,
                page_no=None,
                bbox=None,
                kind="text",
                meta_info=block_meta,
            )
        )

    return blocks
