from __future__ import annotations

from types import SimpleNamespace

from PIL import Image, ImageDraw

from ocr_processor.impl import docling_adapter
from ocr_processor.schemas import BoundingBox


def test_refine_bbox_expands_thin_text_line_from_page_image():
    image = Image.new("RGB", (200, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 180, 50), fill="black")

    page_render = SimpleNamespace(
        image=image,
        scale_x=1.0,
        scale_y=1.0,
        page_width=200.0,
        page_height=120.0,
    )
    thin_bbox = BoundingBox(x0=20.0, y0=44.0, x1=180.0, y1=45.0)

    refined = docling_adapter._refine_bbox_from_page_image(
        bbox=thin_bbox,
        text="Example text",
        page_render=page_render,
    )

    assert refined is not None
    assert refined.x0 <= 21.0
    assert refined.x1 >= 179.0
    assert refined.y0 <= 31.0
    assert refined.y1 >= 49.0


def test_refine_bbox_keeps_regular_box_without_adjustment():
    page_render = SimpleNamespace(
        image=Image.new("RGB", (200, 120), "white"),
        scale_x=1.0,
        scale_y=1.0,
        page_width=200.0,
        page_height=120.0,
    )
    regular_bbox = BoundingBox(x0=10.0, y0=10.0, x1=50.0, y1=30.0)

    refined = docling_adapter._refine_bbox_from_page_image(
        bbox=regular_bbox,
        text="Normal block",
        page_render=page_render,
    )

    assert refined == regular_bbox
