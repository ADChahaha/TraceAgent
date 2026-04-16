from __future__ import annotations

from io import BytesIO
from typing import Any

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter

from ..schemas import BoundingBox, ContentBlock


def convert_with_docling(content: bytes, filename: str) -> Any:
    converter = DocumentConverter()
    return converter.convert(DocumentStream(name=filename, stream=BytesIO(content)))


def build_blocks_from_docling_result(conversion_result: Any) -> list[ContentBlock]:
    document = conversion_result.document
    blocks: list[ContentBlock] = []

    for text_item in document.texts:
        text = getattr(text_item, "text", "").strip()
        if not text:
            continue

        provenance = getattr(text_item, "prov", None) or []
        first_prov = provenance[0] if provenance else None
        bbox = _build_bbox(first_prov)
        page_no = getattr(first_prov, "page_no", None) if first_prov is not None else None

        block_meta: dict[str, Any] = {}
        if first_prov is not None:
            charspan = getattr(first_prov, "charspan", None)
            if charspan is not None:
                block_meta["charspan"] = list(charspan)

        blocks.append(
            ContentBlock(
                text=text,
                page_no=page_no,
                bbox=bbox,
                kind="text",
                meta_info=block_meta,
            )
        )

    return blocks


def _build_bbox(provenance_item: Any) -> BoundingBox | None:
    if provenance_item is None:
        return None

    source_bbox = getattr(provenance_item, "bbox", None)
    if source_bbox is None:
        return None

    return BoundingBox(
        x0=float(source_bbox.l),
        y0=float(source_bbox.t),
        x1=float(source_bbox.r),
        y1=float(source_bbox.b),
    )
