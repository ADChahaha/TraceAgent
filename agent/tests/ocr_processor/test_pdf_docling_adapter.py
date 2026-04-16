from __future__ import annotations

from types import SimpleNamespace

from PIL import Image, ImageDraw

from ocr_processor.impl.pdf import docling_adapter
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


def test_convert_pdf_with_docling_accepts_full_module_tuple(monkeypatch, tmp_path):
    created_streams = []

    class FakeDocumentStream:
        def __init__(self, *, name: str, stream):
            self.name = name
            self.stream = stream
            created_streams.append(self)

    class FakeConverter:
        def convert(self, document_stream):
            return document_stream

    monkeypatch.setattr(docling_adapter, "resolve_docling_artifacts_path", lambda: tmp_path)
    monkeypatch.setattr(
        docling_adapter,
        "_load_docling_pdf_modules",
        lambda: (
            FakeDocumentStream,
            object(),
            object(),
            object(),
            object(),
            object(),
            object(),
        ),
    )
    monkeypatch.setattr(docling_adapter, "_get_pdf_converter", lambda _: FakeConverter())

    result = docling_adapter.convert_pdf_with_docling(b"%PDF-1.4", "sample.pdf")

    assert len(created_streams) == 1
    assert created_streams[0].name == "sample.pdf"
    assert created_streams[0].stream.read() == b"%PDF-1.4"
    assert result is created_streams[0]


def _build_provenance(*, page_no: int, bbox: tuple[float, float, float, float]):
    return SimpleNamespace(
        page_no=page_no,
        bbox=SimpleNamespace(
            l=bbox[0],
            t=bbox[1],
            r=bbox[2],
            b=bbox[3],
            coord_origin=None,
        ),
        charspan=None,
    )


class _FakeTableItem:
    def __init__(
        self,
        *,
        markdown: str,
        page_no: int,
        bbox: tuple[float, float, float, float],
        row_count: int = 0,
        col_count: int = 0,
    ):
        self.prov = [_build_provenance(page_no=page_no, bbox=bbox)]
        self.data = SimpleNamespace(num_rows=row_count, num_cols=col_count)
        self._markdown = markdown

    def export_to_markdown(self, document):
        return self._markdown


def test_build_blocks_emits_table_block_with_markdown():
    markdown = "| Name | Score |\n| --- | --- |\n| Ada | 100 |"
    document = SimpleNamespace(
        texts=[],
        tables=[
            _FakeTableItem(
                markdown=markdown,
                page_no=2,
                bbox=(10.0, 20.0, 210.0, 120.0),
                row_count=2,
                col_count=2,
            )
        ],
        pages={2: SimpleNamespace(size=SimpleNamespace(height=400.0))},
    )
    conversion_result = SimpleNamespace(document=document)

    blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)

    assert len(blocks) == 1
    table_block = blocks[0]
    assert table_block.kind == "table"
    assert table_block.text == markdown
    assert table_block.page_no == 2
    assert table_block.bbox == BoundingBox(x0=10.0, y0=20.0, x1=210.0, y1=120.0)
    assert table_block.meta_info["row_count"] == 2
    assert table_block.meta_info["column_count"] == 2
    assert table_block.meta_info["format"] == "markdown"
    assert table_block.meta_info["docling_label"] == "table"


def test_build_blocks_suppresses_text_nested_inside_table_bbox():
    document = SimpleNamespace(
        texts=[
            SimpleNamespace(
                text="inside table",
                prov=[_build_provenance(page_no=1, bbox=(20.0, 20.0, 80.0, 40.0))],
            ),
            SimpleNamespace(
                text="outside table",
                prov=[_build_provenance(page_no=1, bbox=(120.0, 20.0, 180.0, 40.0))],
            ),
        ],
        tables=[
            _FakeTableItem(
                markdown="| Col |\n| --- |\n| Value |",
                page_no=1,
                bbox=(10.0, 10.0, 100.0, 100.0),
                row_count=2,
                col_count=1,
            )
        ],
        pages={1: SimpleNamespace(size=SimpleNamespace(height=300.0))},
    )
    conversion_result = SimpleNamespace(document=document)

    blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)

    assert len(blocks) == 2
    assert {block.kind for block in blocks} == {"table", "text"}
    assert {block.text for block in blocks} == {
        "| Col |\n| --- |\n| Value |",
        "outside table",
    }


def test_build_blocks_suppresses_text_touching_table_with_bottom_margin():
    document = SimpleNamespace(
        texts=[
            SimpleNamespace(
                text="table spillover",
                prov=[_build_provenance(page_no=1, bbox=(20.0, 96.0, 90.0, 126.0))],
            )
        ],
        tables=[
            _FakeTableItem(
                markdown="| Col |\n| --- |\n| Value |",
                page_no=1,
                bbox=(10.0, 10.0, 100.0, 100.0),
                row_count=2,
                col_count=1,
            )
        ],
        pages={
            1: SimpleNamespace(
                size=SimpleNamespace(width=300.0, height=300.0)
            )
        },
    )
    conversion_result = SimpleNamespace(document=document)

    blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)

    assert len(blocks) == 1
    assert blocks[0].kind == "table"


def test_build_blocks_discards_out_of_page_and_footer_noise():
    document = SimpleNamespace(
        texts=[
            SimpleNamespace(
                text="15",
                prov=[_build_provenance(page_no=1, bbox=(40.0, -20.0, 50.0, -10.0))],
            ),
            SimpleNamespace(
                text="Y",
                prov=[_build_provenance(page_no=1, bbox=(260.0, 260.0, 270.0, 280.0))],
            ),
            SimpleNamespace(
                text="附件",
                prov=[_build_provenance(page_no=1, bbox=(20.0, 20.0, 60.0, 44.0))],
            ),
            SimpleNamespace(
                text="正文内容",
                prov=[_build_provenance(page_no=1, bbox=(40.0, 80.0, 180.0, 120.0))],
            ),
        ],
        tables=[],
        pages={
            1: SimpleNamespace(
                size=SimpleNamespace(width=300.0, height=300.0)
            )
        },
    )
    conversion_result = SimpleNamespace(document=document)

    blocks = docling_adapter.build_blocks_from_docling_result(conversion_result)

    assert [block.text for block in blocks] == ["附件", "正文内容"]
