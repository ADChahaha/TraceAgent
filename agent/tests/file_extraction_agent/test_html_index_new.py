from __future__ import annotations

import pytest

from service.file_extraction_agent.impl.html_index import build_html_document


def test_build_html_document_indexes_existing_ids_and_tree():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">正文</p>
    <table id="dp-table-1">
      <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
      <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
    </table>
    """

    document = build_html_document(html)

    assert "dp-p-1" in document.elements_by_id
    assert document.elements_by_id["dp-h2-1"].type == "SECTION_HEADER"
    assert document.tree[0]["id"] == "dp-h2-1"
    assert document.tree[0]["children"][0]["id"] == "dp-p-1"
    assert document.tree[0]["children"][1]["id"] == "dp-table-1"
    assert document.tables_by_id["dp-table-1"].columns == ["姓名", "学院"]
    assert document.tables_by_id["dp-table-1"].rows == [{"姓名": "张三", "学院": "计算机学院"}]
    assert document.tables_by_id["dp-table-1"].row_ids == ["dp-tr-2"]
    assert document.row_index["dp-tr-2"]["table_id"] == "dp-table-1"


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
    assert document.tree[0]["children"][0]["id"] == "h3"
    assert document.tree[0]["children"][0]["children"][0]["id"] == "p1"
