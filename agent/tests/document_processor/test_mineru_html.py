from service.document_processor.pdf.html import build_html_from_content_list


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

    assert result.startswith("<!doctype html>")
    assert "<style>" in result
    assert "dp-evidence-highlight" in result
    assert 'id="page_001"' in result
    assert "page-number" not in result
    assert "Page 1" not in result
    assert 'id="p001_b000"' in result
    assert 'data-type="title"' in result
    assert "data-level=\"2\"" in result
    assert "data-bbox='[1, 2, 3, 4]'" in result
    assert '<ul id="p001_b001"' in result
    assert 'id="p001_b001_item_000"' in result
    assert '<table id="p001_b002"' in result
    assert 'id="p001_b002_table"' not in result
    assert 'id="p001_b002_tr_000"' in result
    assert "images/table.jpg" not in result
    assert "source:" not in result.lower()


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


def test_build_html_renders_body_subheadings_without_section_nodes():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "3．出願手続"}],
                    "level": 2,
                },
                "bbox": [97, 53, 280, 77],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1）出願手順"}],
                    "level": 2,
                },
                "bbox": [105, 110, 231, 127],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "1．出願期間中に Web 出願システムにより入力してください。",
                        }
                    ]
                },
                "bbox": [94, 720, 589, 736],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [
                        {"type": "text", "content": "3．「エッセイ」については以下の指示に従ってください。"}
                    ],
                    "level": 2,
                },
                "bbox": [92, 486, 563, 502],
            },
        ]
    ]

    result = build_html_from_content_list(pages)

    assert '<section class="section section-level-2" id="p001_b000_section"' in result
    assert "<h2" in result
    assert "3．出願手続</h2>" in result
    assert "1）出願手順</h2>" not in result
    assert "1．出願期間中に Web 出願システムにより入力してください。</h2>" not in result
    assert "3．「エッセイ」については以下の指示に従ってください。</h2>" in result
    assert "<p id=\"p001_b001\"" in result
    assert ">1）出願手順</p>" in result
    assert ">1．出願期間中に Web 出願システムにより入力してください。</p>" in result


def test_build_html_keeps_table_of_contents_entries_out_of_outline_headings():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "目次"}],
                    "level": 2,
                },
                "bbox": [460, 80, 520, 105],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1．募集人員および試験関連日程等"}],
                    "level": 2,
                },
                "bbox": [100, 150, 500, 171],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [{"type": "text", "content": "1）出願受付期間 P.2"}]
                },
                "bbox": [130, 180, 400, 199],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "2．出願資格"}],
                    "level": 2,
                },
                "bbox": [100, 220, 260, 241],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [{"type": "text", "content": "1）出願資格（博士課程前期課程） P.3"}]
                },
                "bbox": [130, 250, 500, 269],
            },
        ],
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1．募集人員および試験関連日程等"}],
                    "level": 2,
                },
                "bbox": [97, 53, 585, 78],
            },
        ],
    ]

    result = build_html_from_content_list(pages)

    assert result.count('class="section section-level-2"') == 2
    assert '<h2 id="p001_b000"' in result
    assert "目次</h2>" in result
    assert "p001_b001_section" not in result
    assert "p001_b003_section" not in result
    assert ">1．募集人員および試験関連日程等</p>" in result
    assert ">2．出願資格</p>" in result
    assert "1）出願受付期間 P.2" in result
    assert '<section class="section section-level-2" id="p002_b000_section"' in result


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

    assert 'id="page_001"' not in result
    assert 'id="page_002"' not in result
    assert 'id="page_003"' in result
    assert 'id="p003_b000"' in result
    assert "SOURCE:" not in result
    assert "images/blank.jpg" not in result


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

    assert 'id="page_001"' not in result
    assert "第2页，共7页" not in result
    assert 'id="page_002"' in result
    assert "正文" in result


def test_build_html_skips_page_footer_noise():
    pages = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "Agreement"}]},
                "bbox": [100, 80, 400, 100],
            },
            {
                "type": "page_footer",
                "content": {"text": "428249v2"},
                "bbox": [114, 940, 171, 950],
            },
        ],
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "正文"}]},
            },
        ],
    ]

    result = build_html_from_content_list(pages)

    assert "Agreement" in result
    assert "正文" in result
    assert "428249v2" not in result
