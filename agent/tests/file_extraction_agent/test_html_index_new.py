from __future__ import annotations

import pytest

from service.file_extraction_agent.impl.html_index import build_html_document


def test_build_html_document_indexes_existing_ids_and_tree():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">正文</p>
    <table id="dp-table-1">
      <caption id="dp-caption-1">学生名单</caption>
      <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
      <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
    </table>
    """

    document = build_html_document(html)

    assert "dp-p-1" in document.elements_by_id
    assert document.elements_by_id["dp-h2-1"].type == "SECTION_HEADER"
    assert document.tree[0]["id"] == "dp-h2-1"
    assert [child["id"] for child in document.tree[0]["children"]] == ["dp-table-1"]
    assert document.tree[0]["children"][0]["label"] == "学生名单"
    assert "text" not in document.tree[0]["children"][0]
    assert document.tables_by_id["dp-table-1"].columns == ["姓名", "学院"]
    assert document.tables_by_id["dp-table-1"].rows == [{"姓名": "张三", "学院": "计算机学院"}]
    assert document.tables_by_id["dp-table-1"].row_ids == ["dp-tr-2"]
    assert document.row_index["dp-tr-2"]["table_id"] == "dp-table-1"


def test_mineru_figure_table_uses_block_id_and_caption_label():
    html = """
    <figure id="p001_b000" data-type="table">
      <div class="caption">文明模范寝室</div>
      <div class="table-wrap">
        <table>
          <tr><td>楼栋</td><td>房间</td><td>平均分</td><td>模范/文明</td></tr>
          <tr><td>18栋</td><td>106</td><td>94.18</td><td>模范寝室</td></tr>
        </table>
      </div>
    </figure>
    """

    document = build_html_document(html)

    assert document.tree == [
        {
            "id": "p001_b000",
            "type": "TABLE",
            "children": [],
            "label": "文明模范寝室",
            "columns": ["楼栋", "房间", "平均分", "模范/文明"],
            "row_count": 1,
        }
    ]
    assert document.elements_by_id["p001_b000"].type == "TABLE"
    assert document.tables_by_id["p001_b000"].columns == ["楼栋", "房间", "平均分", "模范/文明"]
    assert document.row_index["dp-tr-2"]["table_id"] == "p001_b000"


def test_build_html_document_generates_and_indexes_missing_table_row_ids():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <table>
      <tr><th>姓名</th><th>学院</th></tr>
      <tr><td>张三</td><td>计算机学院</td></tr>
      <tr id="dp-tr-2"><td>李四</td><td>自动化学院</td></tr>
      <tr><td>王五</td><td>数学学院</td></tr>
    </table>
    """

    document = build_html_document(html)
    table = document.tables_by_id["dp-table-1"]

    assert table.header_row_id == "dp-tr-1"
    assert table.row_ids == ["dp-tr-3", "dp-tr-2", "dp-tr-4"]
    assert document.row_index["dp-tr-3"]["row"] == {"姓名": "张三", "学院": "计算机学院"}
    assert document.elements_by_id["dp-tr-4"].parent_id == "dp-table-1"


def test_build_html_document_rejects_missing_required_id():
    html = "<p>正文</p>"

    with pytest.raises(ValueError, match="missing id"):
        build_html_document(html)


def test_build_html_document_rejects_duplicate_id():
    html = '<p id="dup">一</p><p id="dup">二</p>'

    with pytest.raises(ValueError, match="duplicate id"):
        build_html_document(html)


def test_heading_levels_create_nested_sections():
    html = """
    <h2 id="h2">一级</h2>
    <h3 id="h3">二级</h3>
    <p id="p1">正文</p>
    """

    document = build_html_document(html)

    assert document.tree[0]["id"] == "h2"
    assert document.tree[0]["text"] == "一级"
    assert document.tree[0]["children"][0]["id"] == "h3"
    assert document.tree[0]["children"][0]["text"] == "二级"
    assert document.tree[0]["children"][0]["children"] == []
