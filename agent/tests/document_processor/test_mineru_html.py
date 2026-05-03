from service.document_processor.mineru_html import (
    build_blocks_from_content_list,
    build_display_html_from_content_list,
    build_html_from_content_list,
    build_markdown_from_content_list,
)


def test_build_html_from_content_list_preserves_ids_metadata_and_tables():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "目 次"}],
                    "level": 2,
                },
                "bbox": [1, 2, 3, 4],
            },
            {
                "type": "index",
                "content": {
                    "list_items": [
                        {
                            "item_content": [
                                {"type": "text", "content": "Ⅰ．入学試験方式"}
                            ]
                        }
                    ]
                },
            },
            {
                "type": "table",
                "content": {
                    "html": "<table><tr><td>専攻</td></tr></table>",
                    "table_footnote": [{"type": "text", "content": "注"}],
                    "image_source": {"path": "images/table.jpg"},
                },
            },
        ]
    ]

    result = build_html_from_content_list(pages)

    assert 'id="page_001"' in result
    assert 'id="p001_b000"' in result
    assert 'data-type="title"' in result
    assert "data-level=\"2\"" in result
    assert "data-bbox='[1, 2, 3, 4]'" in result
    assert 'id="p001_b001_list"' in result
    assert 'id="p001_b001_item_000"' in result
    assert '<table id="p001_b002_table"><tr id="p001_b002_tr_000"><td>専攻</td></tr></table>' in result
    assert "images/table.jpg" in result


def test_build_display_html_wraps_extraction_html_with_replay_style():
    pages = [[{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}]]

    result = build_display_html_from_content_list(pages)

    assert result.startswith("<!doctype html>")
    assert 'id="p001_b000"' in result
    assert "dp-evidence-highlight" in result
    assert "正文" in result


def test_build_blocks_from_content_list_uses_rendered_ids_for_text_list_and_table_rows():
    pages = [
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "本文"}]},
                "bbox": [1, 2, 3, 4],
            },
            {
                "type": "list",
                "content": {
                    "list_items": [
                        {"item_content": [{"type": "text", "content": "出願資格"}]},
                        {"item_content": [{"type": "text", "content": "試験日程"}]},
                    ]
                },
            },
            {
                "type": "table",
                "content": {
                    "html": "<table><tr><th>区分</th><th>日程</th></tr><tr><td>出願</td><td>5月</td></tr></table>",
                    "table_footnote": [{"type": "text", "content": "注"}],
                },
            },
        ]
    ]

    blocks = build_blocks_from_content_list(pages)

    by_id = {block["block_id"]: block for block in blocks}
    assert by_id["p001_b000"]["text"] == "本文"
    assert by_id["p001_b000"]["kind"] == "text"
    assert by_id["p001_b000"]["bbox"] == [1, 2, 3, 4]
    assert by_id["p001_b001"]["text"] == "出願資格\n試験日程"
    assert by_id["p001_b001_item_000"]["text"] == "出願資格"
    assert by_id["p001_b002"]["kind"] == "table"
    assert "区分 | 日程" in by_id["p001_b002"]["text"]
    assert by_id["p001_b002_tr_000"]["kind"] == "table_header"
    assert by_id["p001_b002_tr_001"]["text"] == "出願 | 5月"


def test_build_markdown_from_content_list_keeps_basic_structure():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "募集要項"}],
                    "level": 2,
                },
            },
            {
                "type": "list",
                "content": {
                    "list_items": [
                        {"item_content": [{"type": "text", "content": "修士課程"}]},
                    ]
                },
            },
        ]
    ]

    result = build_markdown_from_content_list(pages)

    assert result == "## 募集要項\n- 修士課程"
