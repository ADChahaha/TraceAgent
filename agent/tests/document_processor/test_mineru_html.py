from service.document_processor.mineru_html import (
    build_blocks_from_content_list,
    build_display_html_from_content_list,
    build_html_from_content_list,
    build_markdown_from_content_list,
    build_semantic_document_from_blocks,
    build_semantic_document_from_content_list,
    extract_inline_id,
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
    assert '<ul id="p001_b001"' in result
    assert 'id="p001_b001_item_000"' in result
    assert '<table id="p001_b002"' in result
    assert 'id="p001_b002_table"' not in result
    assert '<tr id="p001_b002_tr_000"><td>専攻</td></tr>' in result
    assert "images/table.jpg" not in result
    assert "source:" not in result.lower()


def test_build_display_html_wraps_extraction_html_with_replay_style():
    pages = [[{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}]]

    result = build_display_html_from_content_list(pages)

    assert result.startswith("<!doctype html>")
    assert 'id="p001_b000"' in result
    assert "dp-evidence-highlight" in result
    assert "正文" in result


def test_build_html_wraps_h2_and_h3_in_section_hierarchy():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "Contract"}],
                    "level": 1,
                },
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1. Definitions"}],
                    "level": 2,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Definitions body."}
                    ]
                },
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1.1 Included"}],
                    "level": 3,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Included body."}
                    ]
                },
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1.1.1 Detail"}],
                    "level": 4,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Detail body."}
                    ]
                },
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1.2 Excluded"}],
                    "level": 3,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Excluded body."}
                    ]
                },
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "2. Exclusions"}],
                    "level": 2,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Exclusions body."}
                    ]
                },
            },
        ]
    ]

    result = build_html_from_content_list(pages)

    assert '<section class="section section-level-2" id="p001_b001_section"' in result
    assert 'aria-labelledby="p001_b001"' in result
    assert result.index('id="p001_b001_section"') < result.index('id="p001_b001"')
    assert '<section class="subsection subsection-level-3" id="p001_b003_subsection"' in result
    assert 'aria-labelledby="p001_b003"' in result
    assert result.index('id="p001_b003_subsection"') < result.index('id="p001_b003"')
    assert "<h4" not in result
    assert (
        '<p id="p001_b005" class="block block-title" data-element-id="p001_b005" '
        'data-page="1" data-type="title" data-level="4">1.1.1 Detail</p>'
    ) in result

    section_fragment = result.split('id="p001_b001_section"', 1)[1].split(
        'id="p001_b009_section"', 1
    )[0]
    assert 'id="p001_b003_subsection"' in section_fragment
    assert 'id="p001_b007_subsection"' in section_fragment
    assert "Definitions body." in section_fragment

    subsection_fragment = result.split('id="p001_b003_subsection"', 1)[1].split(
        'id="p001_b007_subsection"', 1
    )[0]
    assert "Included body." in subsection_fragment
    assert "1.1.1 Detail" in subsection_fragment
    assert "Detail body." in subsection_fragment

    assert "Exclusions body." in result.split('id="p001_b009_section"', 1)[1]


def test_build_html_skips_pages_without_visible_content():
    pages = [
        [
            {
                "type": "image",
                "content": {"image_source": {"path": "images/blank.jpg"}},
            }
        ],
        [],
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "正文"}]},
            }
        ],
    ]

    result = build_html_from_content_list(pages)
    display_html = build_display_html_from_content_list(pages)

    assert 'id="page_001"' not in result
    assert 'id="page_002"' not in result
    assert 'id="page_003"' in result
    assert 'id="p003_b000"' in result
    assert "SOURCE:" not in display_html
    assert "images/blank.jpg" not in display_html


def test_build_html_skips_pages_with_only_page_number():
    pages = [
        [
            {
                "type": "page_number",
                "content": {"text": "第2页，共7页"},
                "bbox": [455, 939, 551, 963],
            }
        ],
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "正文"}]},
            }
        ],
    ]

    result = build_html_from_content_list(pages)
    blocks = build_blocks_from_content_list(pages)
    markdown = build_markdown_from_content_list(pages)

    assert 'id="page_001"' not in result
    assert "第2页，共7页" not in result
    assert 'id="page_002"' in result
    assert [block["block_id"] for block in blocks] == ["p002_b000"]
    assert markdown == "正文"


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


def test_build_semantic_document_groups_sections_blocks_and_inlines():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "Contract"}],
                    "level": 1,
                },
                "bbox": [1, 2, 3, 4],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "2. Exclusions"}],
                    "level": 2,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "The obligation shall not apply to Confidential Information that:",
                        }
                    ]
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "a) was known to the Receiving Party prior to disclosure; provided that records exist.",
                        }
                    ]
                },
            },
            {
                "type": "page_header",
                "content": {"text": "REPEATED HEADER"},
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "3. Obligations"}],
                    "level": 2,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "The Receiving Party shall protect the information."}
                    ]
                },
            },
        ]
    ]

    result = build_semantic_document_from_content_list(pages)

    assert [section["title"] for section in result["sections"]] == [
        "Contract",
        "2. Exclusions",
        "3. Obligations",
    ]
    exclusions = result["sections"][1]
    assert exclusions["block_ids"] == ["p001_b001", "p001_b002", "p001_b003"]
    assert "2. Exclusions" in exclusions["text"]
    assert "a) was known" in exclusions["text"]
    assert "3. Obligations" not in exclusions["text"]
    assert "REPEATED HEADER" not in exclusions["text"]

    blocks = {block["block_id"]: block for block in result["blocks"]}
    assert blocks["p001_b003"]["type"] == "clause"
    assert blocks["p001_b003"]["clause_marker"] == "a)"
    assert blocks["p001_b003"]["parent_block_id"] == "p001_b002"
    assert blocks["p001_b003"]["section_id"] == exclusions["section_id"]
    assert blocks["p001_b003"]["inline_ids"] == [
        extract_inline_id("was known to the Receiving Party prior to disclosure"),
        extract_inline_id("provided that records exist"),
    ]

    inlines = {inline["inline_id"]: inline for inline in result["inlines"]}
    clause_inline_id = extract_inline_id("was known to the Receiving Party prior to disclosure")
    condition_inline_id = extract_inline_id("provided that records exist")
    assert inlines[clause_inline_id]["type"] == "clause_body"
    assert inlines[clause_inline_id]["text"] == "was known to the Receiving Party prior to disclosure"
    assert inlines[condition_inline_id]["type"] == "condition"
    assert inlines[condition_inline_id]["text"] == "provided that records exist"


def test_extract_inline_id_is_stable_from_normalized_text():
    assert extract_inline_id("Alpha   Beta") == extract_inline_id("Alpha Beta")
    assert extract_inline_id("Alpha Beta") == "inline_d911f80b1165"


def test_build_semantic_document_from_blocks_reuses_cached_mineru_blocks():
    blocks = [
        {
            "block_id": "p001_b000",
            "text": "1. Definitions",
            "page_no": 1,
            "kind": "heading",
            "meta_info": {"mineru_type": "title"},
        },
        {
            "block_id": "p001_b001",
            "text": "Confidential Information means business information.",
            "page_no": 1,
            "kind": "text",
            "meta_info": {"mineru_type": "paragraph"},
        },
        {
            "block_id": "p001_b002",
            "text": "Address\nContact",
            "page_no": 1,
            "kind": "list",
            "meta_info": {"mineru_type": "list"},
        },
        {
            "block_id": "p001_b002_item_000",
            "text": "Address",
            "page_no": 1,
            "kind": "list_item",
            "meta_info": {"mineru_type": "list_item"},
        },
    ]

    result = build_semantic_document_from_blocks(blocks)

    assert result["sections"][0]["title"] == "1. Definitions"
    assert result["sections"][0]["text"] == (
        "1. Definitions\n\nConfidential Information means business information.\n\n- Address"
    )
    assert result["blocks"][1]["section_id"] == result["sections"][0]["section_id"]
    assert "p001_b002" not in {block["block_id"] for block in result["blocks"]}
