from __future__ import annotations

import pytest

from service.file_extraction_agent.impl.html_index import build_html_document


def _documents():
    return [
        {
            "filename": "contract.html",
            "html": """
            <h1 id="t1">项目设计说明</h1>
            <h2 id="h1">背景</h2>
            <p id="p1">这个项目最初是为了抽取字段。</p>
            <p id="p2">这个项目最初是为了验证重名段落。</p>
            <h2 id="h2">背景</h2>
            <ul id="l1">
              <li id="li1">第一项</li>
              <li id="li2">第二项<ul id="l2"><li id="li3">子项</li></ul></li>
            </ul>
            <table id="tbl1">
              <caption id="cap1">费用明细</caption>
              <tr id="tr0"><th>项目</th><th>金额</th></tr>
              <tr id="tr1"><td>服务费</td><td>1000</td></tr>
              <tr id="tr2"><td>押金</td><td>500</td></tr>
            </table>
            """,
        },
        {
            "filename": "contract.html",
            "html": """
            <h1 id="t2">项目设计说明</h1>
            <h2 id="h3">摘要</h2>
            <p id="p3">第二个文件。</p>
            """,
        },
    ]


def test_build_html_document_builds_virtual_tree_for_multiple_documents():
    document = build_html_document(_documents())

    root = document.virtual_root
    assert root.path == "/"
    assert root.path_id == "0000"
    assert [child.name for child in root.children] == [
        "001-contract-项目设计说明",
        "002-contract-项目设计说明",
    ]
    assert [child.path_id for child in root.children] == ["0000.0001", "0000.0002"]
    assert "/001-contract-项目设计说明/001-背景" in document.nodes_by_path
    assert "/001-contract-项目设计说明/002-背景" in document.nodes_by_path
    assert (
        "/001-contract-项目设计说明/001-背景/001-这个项目最初是为了抽取字段.md"
        in document.nodes_by_path
    )
    assert (
        "/001-contract-项目设计说明/001-背景/002-这个项目最初是为了验证重名段落.md"
        in document.nodes_by_path
    )
    assert "/001-contract-项目设计说明/002-背景/001-第一项.list" in document.nodes_by_path
    assert "/001-contract-项目设计说明/002-背景/002-费用明细.table" in document.nodes_by_path


def test_tree_view_respects_depth_and_file_kinds():
    document = build_html_document(_documents())

    depth_one = document.tree_text("/", depth=1)
    assert "0000 /" in depth_one
    assert "0000.0001 contract-项目设计说明/" in depth_one
    assert "001-contract-项目设计说明/" not in depth_one
    assert "背景/" not in depth_one

    depth_three = document.tree_text("/001-contract-项目设计说明", depth=3)
    assert "0000.0001" in depth_three
    assert "/001-contract-项目设计说明/001-背景" not in depth_three
    assert "背景/" in depth_three
    assert "这个项目最初是为了抽取字段.md" in depth_three
    assert "第一项.list" in depth_three
    assert "费用明细.table" in depth_three
    assert "001-这个项目最初是为了抽取字段.md" not in depth_three


def test_path_ids_are_stable_model_visible_locators_for_raw_paths():
    document = build_html_document(_documents())
    path = "/001-contract-项目设计说明/001-背景/001-这个项目最初是为了抽取字段.md"

    path_id = document.path_id(path)

    assert path_id == "0000.0001.0001.0001"
    assert document.resolve_path_id(path_id) == path
    assert document.resolve_path(path_id) == path
    assert document.read_markdown(path_id)["path_id"] == path_id
    assert "path" not in document.read_markdown(path_id)


def test_bracketed_path_ids_are_rejected_instead_of_canonicalized():
    document = build_html_document(_documents())
    legacy_path_id = "[0000.0001.0001.0001]"

    with pytest.raises(ValueError):
        document.resolve_path_id(legacy_path_id)
    with pytest.raises(ValueError):
        document.canonical_path_id(legacy_path_id)
    with pytest.raises(ValueError):
        document.path_id(legacy_path_id)
    with pytest.raises(ValueError):
        document.read_markdown(legacy_path_id)


def test_tree_display_names_decode_percent_encoded_filenames_without_changing_raw_paths():
    document = build_html_document(
        [
            {
                "filename": "Confidentiality%20Agreement.html",
                "html": "<h1>NDA</h1><p>Confidential text.</p>",
            }
        ]
    )

    tree = document.tree_text("/", depth=1)

    assert "0000.0001 Confidentiality Agreement-NDA/" in tree
    assert "Confidentiality%20Agreement" not in tree
    assert "/001-Confidentiality%20Agreement-NDA" in document.nodes_by_path


def test_paragraph_anchors_use_sentence_ids_without_polluting_read():
    document = build_html_document(_documents())
    path = "/001-contract-项目设计说明/001-背景/001-这个项目最初是为了抽取字段.md"

    assert document.read_markdown(path)["text"] == "这个项目最初是为了抽取字段。"
    anchors = document.paragraph_anchors(path)

    assert anchors == [{"id": "S001", "preview": "这个项目最初是为了抽取字段。"}]


def test_list_markdown_uses_item_numbers_and_nested_numbers():
    document = build_html_document(_documents())

    result = document.read_markdown("/001-contract-项目设计说明/002-背景/001-第一项.list")

    assert result["kind"] == "list"
    assert "kind: list" in result["text"]
    assert "- [I001] 第一项" in result["text"]
    assert "- [I002] 第二项 子项" in result["text"]
    assert "  - [I002.001] 子项" in result["text"]
    assert document.validate_evidence(
        [{"path_id": result["path_id"], "items": ["I002", "I002.001"]}]
    ) == []


def test_list_markdown_reports_has_more_against_top_level_items():
    document = build_html_document(
        [
            {
                "filename": "items.html",
                "html": """
                <h1>列表</h1>
                <ul>
                  <li>第一项</li>
                  <li>第二项</li>
                  <li>第三项</li>
                </ul>
                """,
            }
        ]
    )
    path = "/001-items-列表/001-第一项.list"

    first_page = document.read_markdown(path, offset=0, limit=1)
    second_page = document.read_markdown(path, offset=1, limit=1)
    last_page = document.read_markdown(path, offset=2, limit=1)

    assert first_page["has_more"] is True
    assert second_page["has_more"] is True
    assert last_page["has_more"] is False


def test_table_markdown_uses_row_numbers_and_supports_pagination():
    document = build_html_document(_documents())
    path = "/001-contract-项目设计说明/002-背景/002-费用明细.table"

    first_row = document.read_markdown(path, offset=0, limit=1)

    assert first_row["kind"] == "table"
    assert "kind: table" in first_row["text"]
    assert "showing: 1-1" in first_row["text"]
    assert "| R001 | 服务费 | 1000 |" in first_row["text"]
    assert "| R002 | 押金 | 500 |" not in first_row["text"]
    assert document.validate_evidence([{"path_id": document.path_id(path), "rows": ["R002"]}]) == []


def test_query_table_only_accepts_table_paths_and_keeps_original_row_numbers():
    document = build_html_document(_documents())
    path = "/001-contract-项目设计说明/002-背景/002-费用明细.table"

    result = document.query_table(
        path,
        'SELECT "项目", "金额" FROM data WHERE "项目" = \'押金\'',
        offset=0,
        limit=20,
    )

    assert result["kind"] == "table_query"
    assert "kind: table_query" in result["text"]
    assert "| R002 | 押金 | 500 |" in result["text"]
    assert "| R001 | 服务费 | 1000 |" not in result["text"]

    with pytest.raises(ValueError, match=".table"):
        document.query_table(
            "/001-contract-项目设计说明/001-背景/001-这个项目最初是为了抽取字段.md",
            'SELECT "项目" FROM data',
        )
