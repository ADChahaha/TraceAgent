from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
import pypdfium2 as pdfium

from ocr_processor.schemas import BoundingBox, ContentBlock

_AGENT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOCLING_ARTIFACTS_PATH = (
    _AGENT_ROOT / "ocr_processor" / "impl" / "pdf" / "artifacts" / "docling-models"
)
_THIN_TEXT_BBOX_THRESHOLD = 6.0
_PAGE_RENDER_SCALE = 2.0
_TABLE_OVERLAP_THRESHOLD = 0.5
_TABLE_TOP_MARGIN = 12.0
_TABLE_SIDE_MARGIN = 8.0
_TABLE_BOTTOM_MARGIN_MIN = 24.0
_TABLE_BOTTOM_MARGIN_RATIO = 0.25
_FOOTER_NOISE_MARGIN = 200.0
_SHORT_NOISE_TEXT_MAX_LEN = 3
_SMALL_NOISE_BOX_MAX_WIDTH = 40.0
_SMALL_NOISE_BOX_MAX_HEIGHT = 40.0


@dataclass(slots=True)
class _PageRender:
    image: Any
    scale_x: float
    scale_y: float
    page_width: float
    page_height: float


def convert_pdf_with_docling(content: bytes, filename: str) -> Any:
    artifacts_path = resolve_docling_artifacts_path()
    if artifacts_path is None or not artifacts_path.exists():
        raise FileNotFoundError(
            "Docling artifacts were not found. Expected models under "
            f"{_DEFAULT_DOCLING_ARTIFACTS_PATH}"
        )

    converter = _get_pdf_converter(str(artifacts_path))
    return converter.convert(DocumentStream(name=filename, stream=BytesIO(content)))


def resolve_docling_artifacts_path() -> Path | None:
    env_value = os.getenv("DOCLING_ARTIFACTS_PATH")
    if env_value:
        return Path(env_value).expanduser()
    return _DEFAULT_DOCLING_ARTIFACTS_PATH


@lru_cache(maxsize=2)
def _get_pdf_converter(artifacts_path: str) -> DocumentConverter:
    artifacts_root = Path(artifacts_path)
    pipeline_options = PdfPipelineOptions(
        artifacts_path=artifacts_root,
        do_ocr=True,
        ocr_options=RapidOcrOptions(backend="torch"),
        do_table_structure=_has_table_structure_artifacts(artifacts_root),
        do_code_enrichment=False,
        do_formula_enrichment=False,
        do_picture_classification=False,
        do_picture_description=False,
        do_chart_extraction=False,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            ),
        }
    )


def build_blocks_from_docling_result(
    conversion_result: Any,
    *,
    pdf_bytes: bytes | None = None,
) -> list[ContentBlock]:
    document = conversion_result.document
    page_renders = _render_pdf_page_images(pdf_bytes) if pdf_bytes else {}
    table_blocks = _build_table_blocks(document)
    text_blocks = _build_text_blocks(document, page_renders=page_renders)
    table_regions = [
        (block.page_no, block.bbox) for block in table_blocks if block.page_no and block.bbox
    ]
    filtered_text_blocks = [
        block
        for block in text_blocks
        if not _is_text_block_nested_in_table(block, table_regions)
    ]

    blocks = table_blocks + filtered_text_blocks
    blocks.sort(
        key=lambda block: (
            block.page_no if block.page_no is not None else 0,
            block.bbox.y0 if block.bbox is not None else float("inf"),
            block.bbox.x0 if block.bbox is not None else float("inf"),
            0 if block.kind == "table" else 1,
        )
    )
    return blocks


def _build_text_blocks(
    document: Any,
    *,
    page_renders: dict[int, _PageRender],
) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []

    for text_item in getattr(document, "texts", []):
        text = getattr(text_item, "text", "").strip()
        if not text:
            continue

        provenance = getattr(text_item, "prov", None) or []
        first_prov = provenance[0] if provenance else None
        page_no = (
            getattr(first_prov, "page_no", None) if first_prov is not None else None
        )
        page_size = _resolve_page_size(document=document, page_no=page_no)
        page_height = page_size[1] if page_size is not None else None
        bbox = _build_bbox(first_prov, page_height=page_height)
        if bbox is not None and page_no is not None:
            bbox = _refine_bbox_from_page_image(
                bbox=bbox,
                text=text,
                page_render=page_renders.get(page_no),
            )
            bbox = _normalize_bbox_to_page(bbox, page_size=page_size)
            if bbox is None:
                continue
            if _is_noise_text_block(text=text, bbox=bbox, page_size=page_size):
                continue

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


def _build_table_blocks(document: Any) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []

    for table_item in getattr(document, "tables", []):
        markdown = _export_table_markdown(table_item, document)
        if not markdown:
            continue

        provenance = getattr(table_item, "prov", None) or []
        first_prov = provenance[0] if provenance else None
        page_no = (
            getattr(first_prov, "page_no", None) if first_prov is not None else None
        )
        page_height = _resolve_page_height(document=document, page_no=page_no)
        bbox = _build_bbox(first_prov, page_height=page_height)
        table_data = getattr(table_item, "data", None)

        blocks.append(
            ContentBlock(
                text=markdown,
                page_no=page_no,
                bbox=bbox,
                kind="table",
                meta_info={
                    "row_count": getattr(table_data, "num_rows", None),
                    "column_count": getattr(table_data, "num_cols", None),
                    "format": "markdown",
                },
            )
        )

    return blocks


def _export_table_markdown(table_item: Any, document: Any) -> str:
    export_to_markdown = getattr(table_item, "export_to_markdown", None)
    if export_to_markdown is None:
        return ""

    markdown = export_to_markdown(document)
    return markdown.strip() if isinstance(markdown, str) else ""


def _is_text_block_nested_in_table(
    block: ContentBlock,
    table_regions: list[tuple[int, BoundingBox]],
) -> bool:
    if block.kind != "text" or block.page_no is None or block.bbox is None:
        return False

    for table_page_no, table_bbox in table_regions:
        if table_page_no != block.page_no:
            continue
        expanded_table_bbox = _expand_table_bbox(table_bbox)
        if _overlap_ratio(block.bbox, expanded_table_bbox) >= _TABLE_OVERLAP_THRESHOLD:
            return True

    return False


def _overlap_ratio(inner_bbox: BoundingBox, outer_bbox: BoundingBox) -> float:
    overlap_width = min(inner_bbox.x1, outer_bbox.x1) - max(inner_bbox.x0, outer_bbox.x0)
    overlap_height = min(inner_bbox.y1, outer_bbox.y1) - max(inner_bbox.y0, outer_bbox.y0)
    if overlap_width <= 0 or overlap_height <= 0:
        return 0.0

    overlap_area = overlap_width * overlap_height
    inner_area = (inner_bbox.x1 - inner_bbox.x0) * (inner_bbox.y1 - inner_bbox.y0)
    if inner_area <= 0:
        return 0.0

    return overlap_area / inner_area


def _has_table_structure_artifacts(artifacts_path: Path) -> bool:
    return any(artifacts_path.glob("**/tableformer/*/tm_config.json"))


def _normalize_bbox_to_page(
    bbox: BoundingBox,
    *,
    page_size: tuple[float, float] | None,
) -> BoundingBox | None:
    if page_size is None:
        return bbox

    page_width, page_height = page_size
    if bbox.x1 <= 0 or bbox.y1 <= 0 or bbox.x0 >= page_width or bbox.y0 >= page_height:
        return None

    normalized_bbox = BoundingBox(
        x0=max(0.0, min(page_width, bbox.x0)),
        y0=max(0.0, min(page_height, bbox.y0)),
        x1=max(0.0, min(page_width, bbox.x1)),
        y1=max(0.0, min(page_height, bbox.y1)),
    )
    if normalized_bbox.x1 <= normalized_bbox.x0 or normalized_bbox.y1 <= normalized_bbox.y0:
        return None

    return normalized_bbox


def _is_noise_text_block(
    *,
    text: str,
    bbox: BoundingBox,
    page_size: tuple[float, float] | None,
) -> bool:
    if page_size is None:
        return False

    normalized_text = re.sub(r"\s+", "", text)
    if not normalized_text:
        return True

    if len(normalized_text) > _SHORT_NOISE_TEXT_MAX_LEN:
        return False

    width = bbox.x1 - bbox.x0
    height = bbox.y1 - bbox.y0
    if width > _SMALL_NOISE_BOX_MAX_WIDTH or height > _SMALL_NOISE_BOX_MAX_HEIGHT:
        return False

    if _looks_like_meaningful_short_text(normalized_text):
        return False

    _, page_height = page_size
    return bbox.y0 >= page_height - _FOOTER_NOISE_MARGIN


def _looks_like_meaningful_short_text(text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]{2,}", text):
        return True
    if re.search(r"[A-Za-z]{3,}", text):
        return True
    if re.search(r"\d{4,}", text):
        return True
    return bool(re.search(r"第\d+页", text))


def _expand_table_bbox(table_bbox: BoundingBox) -> BoundingBox:
    table_height = table_bbox.y1 - table_bbox.y0
    bottom_margin = max(_TABLE_BOTTOM_MARGIN_MIN, table_height * _TABLE_BOTTOM_MARGIN_RATIO)
    return BoundingBox(
        x0=table_bbox.x0 - _TABLE_SIDE_MARGIN,
        y0=max(0.0, table_bbox.y0 - _TABLE_TOP_MARGIN),
        x1=table_bbox.x1 + _TABLE_SIDE_MARGIN,
        y1=table_bbox.y1 + bottom_margin,
    )


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
    provenance_item: Any, *, page_height: float | None
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


def _render_pdf_page_images(pdf_bytes: bytes) -> dict[int, _PageRender]:
    pdf_document = pdfium.PdfDocument(BytesIO(pdf_bytes))
    page_renders: dict[int, _PageRender] = {}

    for page_index in range(len(pdf_document)):
        page = pdf_document[page_index]
        page_width, page_height = page.get_size()
        image = page.render(scale=_PAGE_RENDER_SCALE).to_pil()
        page_renders[page_index + 1] = _PageRender(
            image=image,
            scale_x=image.width / page_width,
            scale_y=image.height / page_height,
            page_width=float(page_width),
            page_height=float(page_height),
        )

    return page_renders


def _refine_bbox_from_page_image(
    *,
    bbox: BoundingBox,
    text: str,
    page_render: _PageRender | None,
) -> BoundingBox:
    height = bbox.y1 - bbox.y0
    if page_render is None or height >= _THIN_TEXT_BBOX_THRESHOLD:
        return bbox

    center_y = (bbox.y0 + bbox.y1) / 2
    margin_x = max(2.0, min(10.0, len(text) * 0.25))
    margin_y = max(12.0, _THIN_TEXT_BBOX_THRESHOLD * 2)

    left = max(0, int((bbox.x0 - margin_x) * page_render.scale_x))
    top = max(0, int((center_y - margin_y) * page_render.scale_y))
    right = min(
        page_render.image.width,
        int((bbox.x1 + margin_x) * page_render.scale_x),
    )
    bottom = min(
        page_render.image.height,
        int((center_y + margin_y) * page_render.scale_y),
    )
    if left >= right or top >= bottom:
        return bbox

    crop = page_render.image.crop((left, top, right, bottom)).convert("L")
    binary = crop.point(lambda value: 255 if value < 220 else 0)
    refined_bbox = binary.getbbox()
    if refined_bbox is None:
        return bbox

    refined_left = left + refined_bbox[0]
    refined_top = top + refined_bbox[1]
    refined_right = left + refined_bbox[2]
    refined_bottom = top + refined_bbox[3]

    padding_px = 1
    refined_left = max(0, refined_left - padding_px)
    refined_top = max(0, refined_top - padding_px)
    refined_right = min(page_render.image.width, refined_right + padding_px)
    refined_bottom = min(page_render.image.height, refined_bottom + padding_px)

    return BoundingBox(
        x0=refined_left / page_render.scale_x,
        y0=refined_top / page_render.scale_y,
        x1=refined_right / page_render.scale_x,
        y1=refined_bottom / page_render.scale_y,
    )
