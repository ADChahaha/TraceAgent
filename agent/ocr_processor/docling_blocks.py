from __future__ import annotations

import re
from typing import Any

from ocr_processor.schemas import BoundingBox, ContentBlock

_FILTERED_LABELS = {
    "caption",
    "document_index",
    "footnote",
    "formula",
    "marker",
    "page_footer",
    "page_header",
    "picture",
}
_HEADING_LABELS = {"field_heading", "section_header", "title"}
_LIST_LABELS = {"list_item"}
_TABLE_LABELS = {"table"}
_TEXT_LABELS = {"paragraph", "text"}


def build_blocks_from_docling_document(document: Any) -> list[ContentBlock]:
    if hasattr(document, "iterate_items"):
        blocks = _build_blocks_from_iterable_items(document)
    else:
        blocks = _build_blocks_from_flat_document(document)

    return _dedupe_adjacent_blocks(blocks)


def _build_blocks_from_iterable_items(document: Any) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []

    for item, level in document.iterate_items():
        block = _build_block_from_docling_item(
            item=item,
            document=document,
            level=level,
        )
        if block is not None:
            blocks.append(block)

    return blocks


def _build_blocks_from_flat_document(document: Any) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []

    for table_item in getattr(document, "tables", []):
        block = _build_flat_table_block(item=table_item, document=document)
        if block is not None:
            blocks.append(block)

    for text_item in getattr(document, "texts", []):
        block = _build_block_from_docling_item(item=text_item, document=document, level=1)
        if block is not None:
            blocks.append(block)

    blocks.sort(
        key=lambda block: (
            block.page_no if block.page_no is not None else 0,
            block.bbox.y0 if block.bbox is not None else float("inf"),
            block.bbox.x0 if block.bbox is not None else float("inf"),
            0 if block.kind == "table" else 1,
        )
    )
    return blocks


def _build_flat_table_block(item: Any, document: Any) -> ContentBlock | None:
    text = _export_table_markdown(item, document)
    if not text:
        return None

    provenance = getattr(item, "prov", None) or []
    first_prov = provenance[0] if provenance else None
    page_no = getattr(first_prov, "page_no", None) if first_prov is not None else None
    page_height = _resolve_page_height(document=document, page_no=page_no)
    bbox = _build_bbox(first_prov, page_height=page_height)
    table_data = getattr(item, "data", None)

    return ContentBlock(
        text=text,
        page_no=page_no,
        bbox=bbox,
        kind="table",
        meta_info={
            "docling_label": "table",
            "docling_level": 1,
            "row_count": getattr(table_data, "num_rows", None),
            "column_count": getattr(table_data, "num_cols", None),
            "format": "markdown",
        },
    )


def _build_block_from_docling_item(
    *,
    item: Any,
    document: Any,
    level: int,
) -> ContentBlock | None:
    label = _get_item_label(item)
    if label in _FILTERED_LABELS:
        return None

    if label in _TABLE_LABELS:
        text = _export_table_markdown(item, document)
        kind = "table"
    else:
        text = _normalize_text(getattr(item, "text", ""))
        kind = _map_label_to_kind(label)

    if not text:
        return None

    provenance = getattr(item, "prov", None) or []
    first_prov = provenance[0] if provenance else None
    page_no = getattr(first_prov, "page_no", None) if first_prov is not None else None
    page_height = _resolve_page_height(document=document, page_no=page_no)
    bbox = _build_bbox(first_prov, page_height=page_height)

    block_meta: dict[str, Any] = {
        "docling_label": label,
        "docling_level": level,
    }
    self_ref = getattr(item, "self_ref", None)
    if self_ref:
        block_meta["docling_ref"] = str(self_ref)
    if first_prov is not None:
        charspan = getattr(first_prov, "charspan", None)
        if charspan is not None:
            block_meta["charspan"] = list(charspan)

    if kind == "table":
        table_data = getattr(item, "data", None)
        block_meta["row_count"] = getattr(table_data, "num_rows", None)
        block_meta["column_count"] = getattr(table_data, "num_cols", None)
        block_meta["format"] = "markdown"

    return ContentBlock(
        text=text,
        page_no=page_no,
        bbox=bbox,
        kind=kind,
        meta_info=block_meta,
    )


def _map_label_to_kind(label: str | None) -> str:
    if label in _HEADING_LABELS:
        return "heading"
    if label in _LIST_LABELS:
        return "list_item"
    if label in _TABLE_LABELS:
        return "table"
    if label in _TEXT_LABELS:
        return "text"
    return "text"


def _get_item_label(item: Any) -> str | None:
    label = getattr(item, "label", None)
    if label is None:
        return None
    return getattr(label, "value", str(label)).lower()


def _export_table_markdown(table_item: Any, document: Any) -> str:
    export_to_markdown = getattr(table_item, "export_to_markdown", None)
    if export_to_markdown is None:
        return ""

    markdown = export_to_markdown(document)
    return markdown.strip() if isinstance(markdown, str) else ""


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_adjacent_blocks(blocks: list[ContentBlock]) -> list[ContentBlock]:
    deduped: list[ContentBlock] = []
    previous_signature: tuple[str, str] | None = None

    for block in blocks:
        signature = (block.kind, block.text)
        if signature == previous_signature:
            continue
        deduped.append(block)
        previous_signature = signature

    return deduped


def _resolve_page_height(document: Any, page_no: int | None) -> float | None:
    page_size = _resolve_page_size(document=document, page_no=page_no)
    if page_size is None:
        return None

    return page_size[1]


def _resolve_page_size(
    document: Any,
    page_no: int | None,
) -> tuple[float, float] | None:
    if page_no is None:
        return None

    pages = getattr(document, "pages", None)
    if pages is None:
        return None

    page = pages.get(page_no)
    if page is None:
        return None

    size = getattr(page, "size", None)
    if size is None:
        return None

    width = getattr(size, "width", None)
    height = getattr(size, "height", None)
    if width is None or height is None:
        return None

    return float(width), float(height)


def _build_bbox(
    provenance_item: Any,
    *,
    page_height: float | None,
) -> BoundingBox | None:
    if provenance_item is None:
        return None

    source_bbox = getattr(provenance_item, "bbox", None)
    if source_bbox is None:
        return None

    coord_origin = getattr(source_bbox, "coord_origin", None)
    origin_name = (
        getattr(coord_origin, "value", str(coord_origin)).lower()
        if coord_origin is not None
        else None
    )

    if origin_name == "bottomleft" and page_height is not None:
        return BoundingBox(
            x0=float(source_bbox.l),
            y0=float(page_height - source_bbox.t),
            x1=float(source_bbox.r),
            y1=float(page_height - source_bbox.b),
        )

    return BoundingBox(
        x0=float(source_bbox.l),
        y0=float(source_bbox.t),
        x1=float(source_bbox.r),
        y1=float(source_bbox.b),
    )
