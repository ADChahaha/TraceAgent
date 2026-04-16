from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ocr_processor.impl.docling_blocks import build_blocks_from_docling_document


class _FakeTableItem:
    def __init__(self, markdown: str):
        self.label = SimpleNamespace(value="table")
        self.text = None
        self.prov = []
        self.data = SimpleNamespace(num_rows=2, num_cols=2)
        self.self_ref = "#/tables/0"
        self._markdown = markdown

    def export_to_markdown(self, document):
        return self._markdown


def _fake_item(*, label: str, text: str | None, level: int):
    item = SimpleNamespace(
        label=SimpleNamespace(value=label),
        text=text,
        prov=[],
        self_ref=f"#/{label}/{level}",
    )
    return item, level


def test_build_blocks_from_docling_document_maps_items_to_our_blocks():
    table_item = _FakeTableItem("| Name | Score |\n| --- | --- |\n| Ada | 100 |")
    document = SimpleNamespace(
        iterate_items=lambda: iter(
            [
                _fake_item(label="title", text="Document Title", level=1),
                _fake_item(label="text", text="Paragraph body", level=1),
                _fake_item(label="picture", text=None, level=1),
                (table_item, 1),
            ]
        )
    )

    blocks = build_blocks_from_docling_document(document)

    assert [block.kind for block in blocks] == ["heading", "text", "table"]
    assert blocks[0].text == "Document Title"
    assert blocks[1].text == "Paragraph body"
    assert blocks[2].text.startswith("| Name | Score |")
    assert blocks[2].meta_info["row_count"] == 2
