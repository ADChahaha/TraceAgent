"""MinerU HTML 过滤测试：目录页降级、空白页、纯页码页与页脚噪声剔除。"""

from document_service.document_processor.pdf.html import build_html_from_content_list


def test_build_html_keeps_table_of_contents_entries_out_of_outline_headings():
    pages = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "目次"}], "level": 2},
                "bbox": [460, 80, 520, 105],
            },
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "1．募集人員および試験関連日程等"}], "level": 2},
                "bbox": [100, 150, 500, 171],
            },
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "1）出願受付期間 P.2"}]},
                "bbox": [130, 180, 400, 199],
            },
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "2．出願資格"}], "level": 2},
                "bbox": [100, 220, 260, 241],
            },
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "1）出願資格（博士課程前期課程） P.3"}]},
                "bbox": [130, 250, 500, 269],
            },
        ],
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "1．募集人員および試験関連日程等"}], "level": 2},
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
        [{"type": "image", "content": {"image_source": {"path": "images/blank.jpg"}}}],
        [],
        [{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}],
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
        [{"type": "page_number", "content": {"text": "第2页，共7页"}, "bbox": [455, 939, 551, 963]}],
        [{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}],
    ]

    result = build_html_from_content_list(pages)

    assert 'id="page_001"' not in result
    assert "第2页，共7页" not in result
    assert 'id="page_002"' in result
    assert "正文" in result


def test_build_html_skips_page_footer_noise():
    pages = [
        [
            {"type": "title", "content": {"title_content": [{"type": "text", "content": "Agreement"}]}, "bbox": [100, 80, 400, 100]},
            {"type": "page_footer", "content": {"text": "428249v2"}, "bbox": [114, 940, 171, 950]},
        ],
        [{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "正文"}]}}],
    ]

    result = build_html_from_content_list(pages)

    assert "Agreement" in result
    assert "正文" in result
    assert "428249v2" not in result
