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
    assert "page-number" not in result


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


def test_build_markdown_keeps_deadline_title_as_heading():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "3）出願書類"}],
                    "level": 2,
                },
                "bbox": [105, 677, 231, 695],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "・PDF ファイルは次の提出期限までに、「マイページ」上にて、提出してください。",
                        }
                    ]
                },
                "bbox": [147, 171, 811, 186],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [
                        {
                            "type": "text",
                            "content": "提出期限 2025 年9月9日（火） 日本時間 23:59 まで",
                        }
                    ],
                    "level": 2,
                },
                "bbox": [176, 191, 647, 206],
            },
        ]
    ]

    html = build_html_from_content_list(pages)
    markdown = build_markdown_from_content_list(pages)

    assert "## 提出期限 2025 年9月9日（火） 日本時間 23:59 まで" in markdown
    assert "3）出願書類" in markdown
    assert "提出期限 2025 年9月9日（火） 日本時間 23:59 まで</h2>" in html


def test_build_markdown_keeps_compact_numbered_title_as_heading():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "Ⅰ．入学試験方式・募集人数・日程等"}],
                    "level": 2,
                },
                "bbox": [88, 120, 610, 145],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "2.日程"}],
                    "level": 2,
                },
                "bbox": [105, 188, 180, 204],
            },
        ]
    ]

    html = build_html_from_content_list(pages)
    markdown = build_markdown_from_content_list(pages)

    assert "## 2.日程" in markdown
    assert "## Ⅰ．入学試験方式・募集人数・日程等" in markdown
    assert "2.日程</h2>" in html


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
    assert "<!-- Cluster summary:" not in markdown
    assert "<!-- cluster=" not in markdown
    assert "正文" in markdown
    assert "第2页，共7页" not in markdown


def test_build_outputs_skip_page_footer_noise():
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

    html = build_html_from_content_list(pages)
    display_html = build_display_html_from_content_list(pages)
    blocks = build_blocks_from_content_list(pages)
    markdown = build_markdown_from_content_list(pages)

    assert "Agreement" in html
    assert "正文" in html
    assert "428249v2" not in html
    assert "428249v2" not in display_html
    assert [block["block_id"] for block in blocks] == ["p001_b000", "p002_b000"]
    assert all(block["text"] != "428249v2" for block in blocks)
    assert "428249v2" not in markdown


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
    assert by_id["p001_b001"]["kind"] == "list"
    assert by_id["p001_b002"]["kind"] == "table"
    assert "区分 | 日程" in by_id["p001_b002"]["text"]
    assert all(block["kind"] not in {"list_item", "table_header", "table_row"} for block in blocks)


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

    assert "<!-- Cluster summary:" not in result
    assert "<!-- cluster=" not in result
    assert "## 募集要項" in result
    assert "- 修士課程" in result


def test_build_markdown_from_content_list_embeds_clustered_block_structure():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "立教大学大学院入試要項"}],
                    "level": 1,
                },
                "bbox": [122, 210, 875, 367],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [
                        {
                            "type": "text",
                            "content": "人工知能科学研究科（一般入学試験）博士課程前期課程",
                        }
                    ],
                    "level": 1,
                },
                "bbox": [169, 386, 825, 542],
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
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "本研究科博士課程前期課程の入学試験は一般入学試験として実施します。",
                        }
                    ]
                },
                "bbox": [88, 88, 907, 120],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1）出願受付期間"}],
                    "level": 2,
                },
                "bbox": [105, 110, 270, 126],
            },
            {
                "type": "table",
                "content": {
                    "html": "<table><tr><td>出願受付期間</td><td>2025年8月14日</td></tr></table>",
                },
                "bbox": [90, 216, 907, 241],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "【募集人員および試験日程に関する注意事項】"}],
                    "level": 2,
                },
                "bbox": [99, 400, 465, 416],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "(1) 募集人員は別の時期に募集する人数を含みます。"}
                    ]
                },
                "bbox": [90, 430, 564, 461],
            },
        ],
    ]

    result = build_markdown_from_content_list(pages)

    assert "<!-- Cluster summary:" not in result
    assert "<!-- cluster=" not in result
    assert "type=title" not in result
    assert "# 立教大学大学院入試要項" in result
    assert "# 人工知能科学研究科（一般入学試験）博士課程前期課程" in result
    assert "## 1．募集人員および試験関連日程等" in result
    assert "1）出願受付期間" in result
    assert "【募集人員および試験日程に関する注意事項】" in result
    assert "本研究科博士課程前期課程の入学試験は一般入学試験として実施します。" in result
    assert "<table><tr><td>出願受付期間</td><td>2025年8月14日</td></tr></table>" in result
    assert "markdown_title_level" not in result


def test_build_markdown_from_content_list_separates_true_titles_from_body_subheadings():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "2026 年度"}],
                    "level": 1,
                },
                "bbox": [122, 210, 875, 367],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "立教大学大学院入試要項"}],
                    "level": 1,
                },
                "bbox": [122, 210, 875, 367],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [
                        {
                            "type": "text",
                            "content": "人工知能科学研究科（一般入学試験・社会人入学試験）（秋季実施分）博士課程前期課程",
                        }
                    ],
                    "level": 1,
                },
                "bbox": [169, 386, 825, 542],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "本研究科博士課程前期課程の入学試験は一般入学試験として実施します。",
                        }
                    ]
                },
                "bbox": [88, 88, 907, 120],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1．募集人員および試験関連日程等"}],
                    "level": 2,
                },
                "bbox": [97, 53, 585, 78],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "本研究科博士課程前期課程の入学試験は一般入学試験として実施します。",
                        }
                    ]
                },
                "bbox": [88, 88, 907, 120],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "1）出願受付期間"}],
                    "level": 2,
                },
                "bbox": [105, 110, 270, 126],
            },
            {
                "type": "table",
                "content": {
                    "html": "<table><tr><td>出願受付期間</td><td>2025年8月14日</td></tr></table>",
                },
                "bbox": [90, 216, 907, 241],
            },
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "【募集人員および試験日程に関する注意事項】"}],
                    "level": 2,
                },
                "bbox": [99, 400, 465, 416],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "(1) 募集人員は別の時期に募集する人数を含みます。"}
                    ]
                },
                "bbox": [90, 430, 564, 461],
            },
        ]
    ]

    result = build_markdown_from_content_list(pages)

    assert "# 立教大学大学院入試要項" in result
    assert "# 人工知能科学研究科（一般入学試験・社会人入学試験）（秋季実施分）博士課程前期課程" in result
    assert "## 1．募集人員および試験関連日程等" in result
    assert "1）出願受付期間" in result
    assert "【募集人員および試験日程に関する注意事項】" in result
    assert "**1）出願受付期間**" not in result
    assert "**【募集人員および試験日程に関する注意事項】**" not in result
    assert "#### 1）出願受付期間" not in result
    assert "#### 【募集人員および試験日程に関する注意事項】" not in result
    assert "本研究科博士課程前期課程の入学試験は一般入学試験として実施します。" in result
    assert "<table><tr><td>出願受付期間</td><td>2025年8月14日</td></tr></table>" in result


def test_build_markdown_from_content_list_promotes_numbered_paragraph_body_items():
    pages = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "3）出願書類"}],
                    "level": 2,
                },
                "bbox": [105, 677, 231, 695],
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
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {
                            "type": "text",
                            "content": "2．Web 出願システムでは、志願票入力と写真のアップロード、および選考料の納入が完了すると、「マイページ」が生成されます。",
                        }
                    ]
                },
                "bbox": [92, 45, 892, 82],
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

    result = build_markdown_from_content_list(pages)

    assert "3）出願書類" in result
    assert "1．出願期間中に Web 出願システムにより入力してください。" in result
    assert "2．Web 出願システムでは、志願票入力と写真のアップロード、および選考料の納入が完了すると、「マイページ」が生成されます。" in result
    assert "3．「エッセイ」については以下の指示に従ってください。" in result
    assert "**3）出願書類**" not in result
    assert "**1．出願期間中に Web 出願システムにより入力してください。**" not in result
    assert "**2．Web 出願システムでは、志願票入力と写真のアップロード、および選考料の納入が完了すると、「マイページ」が生成されます。**" not in result
    assert "**3．「エッセイ」については以下の指示に従ってください。**" not in result
    assert "## 3．「エッセイ」については以下の指示に従ってください。" in result
