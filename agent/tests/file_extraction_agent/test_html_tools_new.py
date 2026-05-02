from __future__ import annotations

from types import SimpleNamespace

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_tools import (
    build_tools,
    _finish,
    _overview,
    _paragraph_extraction,
    _read_element,
    _read_section,
    _set_field,
    _table_extraction,
)


def _state():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">联系人：李老师 电话：12345</p>
    <h3 id="dp-h3-1">名单</h3>
    <p id="dp-p-2">名单如下。</p>
    <ul id="dp-ul-1">
      <li id="dp-li-1">第一条很长很长很长很长很长很长很长很长很长很长很长很长</li>
      <li id="dp-li-2">第二条</li>
      <li id="dp-li-3">第三条</li>
      <li id="dp-li-4">第四条</li>
    </ul>
    <table id="dp-table-1">
      <caption id="dp-caption-1">学生名单</caption>
      <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
      <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
      <tr id="dp-tr-3"><td>李四</td><td>自动化学院</td></tr>
    </table>
    """
    return SimpleNamespace(
        document=build_html_document(html),
        task_spec=SimpleNamespace(
            fields=[
                SimpleNamespace(name="student_name", type="string", required=True),
                SimpleNamespace(name="contact_phone", type="string", required=False),
            ]
        ),
        field_states={},
        actions=[],
        observed_evidence_ids=set(),
    )


def test_overview_returns_document_tree():
    result = _overview(_state())

    assert result["tree"][0]["id"] == "dp-h2-1"
    assert result["tree"][0]["text"] == "通知"
    table_node = _find_tree_node(result["tree"], "dp-table-1")
    assert table_node is not None
    assert table_node["id"] == "dp-table-1"
    assert table_node["type"] == "TABLE"
    assert table_node["table_name"] == "学生名单"
    assert table_node["columns"] == ["姓名", "学院"]
    assert table_node["row_count"] == 2
    assert "text" not in table_node


def test_read_element_returns_text_element():
    result = _read_element(_state(), "dp-p-1")

    assert result["id"] == "dp-p-1"
    assert result["type"] == "TEXT"
    assert result["html"] == '<text id="dp-p-1">联系人：李老师 电话：12345</text>'
    assert result["evidence_ids"] == ["dp-p-1"]


def test_read_element_table_returns_header_only():
    result = _read_element(_state(), "dp-table-1")

    assert result["id"] == "dp-table-1"
    assert result["type"] == "TABLE"
    assert result["html"] == (
        '<table-ref id="dp-table-1" rows="2" header-row-id="dp-tr-1" '
        'columns="姓名 | 学院" />'
    )
    assert result["evidence_ids"] == ["dp-table-1"]
    assert "rows" not in result


def test_read_section_returns_section_content_and_table_refs_by_depth():
    result = _read_section(_state(), "dp-h2-1", depth=1)

    assert result["section_id"] == "dp-h2-1"
    assert result["html"].startswith('<section id="dp-h2-1" title="通知" depth="1">')
    assert '<text id="dp-p-1">联系人：李老师 电话：12345</text>' in result["html"]
    assert '<heading id="dp-h3-1">名单</heading>' in result["html"]
    assert '<list-ref id="dp-ul-1" items="4">' in result["html"]
    assert '<item-ref id="dp-li-1">' in result["html"]
    assert '<truncated remaining="1" />' in result["html"]
    assert (
        '<table-ref id="dp-table-1" rows="2" header-row-id="dp-tr-1" columns="姓名 | 学院" />'
        in result["html"]
    )
    assert "dp-table-1" in result["evidence_ids"]
    assert "第一条很长很长很长很长很长很长很长很长很长很长很长很长" in result["html"]


def test_table_extraction_selects_rows_with_evidence_ids():
    result = _table_extraction(
        _state(),
        "dp-table-1",
        "SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
    )

    assert result["rows"] == [
        {
            "row_id": "dp-tr-2",
            "values": {"姓名": "张三"},
            "evidence_ids": ["dp-table-1", "dp-tr-2"],
        }
    ]


def test_table_extraction_row_evidence_ids_can_be_used_by_set_field():
    state = _state()
    result = _table_extraction(
        state,
        "dp-table-1",
        "SELECT 姓名 FROM data WHERE 学院 = '自动化学院'",
    )

    row = result["rows"][0]
    set_result = _set_field(
        state,
        "student_name",
        row["values"]["姓名"],
        row["evidence_ids"],
        "resolved",
        None,
    )

    assert row["row_id"] == "dp-tr-3"
    assert row["evidence_ids"] == ["dp-table-1", "dp-tr-3"]
    assert set_result["ok"] is True
    assert state.field_states["student_name"]["evidence_ids"] == [
        "dp-table-1",
        "dp-tr-3",
    ]


def test_table_extraction_returns_sql_errors_for_model_retry():
    result = _table_extraction(
        _state(),
        "dp-table-1",
        "SELECT 不存在 FROM data",
    )

    assert result["ok"] is False
    assert "no such column" in result["error"]
    assert result["columns"] == ["姓名", "学院"]
    assert "double quotes" in result["sql_hint"]


def test_paragraph_extraction_returns_all_regex_matches():
    result = _paragraph_extraction(_state(), "dp-p-1", r"\d+")

    assert result["matches"][0]["text"] == "12345"
    assert result["matches"][0]["evidence_ids"] == ["dp-p-1"]


def test_set_field_records_value_and_finish_validates_required_fields():
    state = _state()
    _table_extraction(
        state,
        "dp-table-1",
        "SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
    )

    set_result = _set_field(
        state,
        "student_name",
        "张三",
        ["dp-table-1", "dp-tr-2"],
        "resolved",
        None,
    )
    finish_result = _finish(state)

    assert set_result["ok"] is True
    assert state.field_states["student_name"]["value"] == "张三"
    assert finish_result == {"ok": True, "errors": []}


def test_set_field_rejects_unobserved_evidence_ids():
    state = _state()

    result = _set_field(
        state,
        "student_name",
        "张三",
        ["dp-table-1", "dp-tr-2"],
        "resolved",
        None,
    )

    assert result["ok"] is False
    assert "observed" in result["errors"][0]["message"]


def test_finish_fails_missing_required_field():
    result = _finish(_state())

    assert result["ok"] is False
    assert result["errors"][0]["field"] == "student_name"


def test_build_tools_exposes_model_facing_docstrings_without_state_argument():
    tools = build_tools(_state())
    names = [_tool_name(tool) for tool in tools]

    assert names == [
        "read_element",
        "read_section",
        "table_extraction",
        "paragraph_extraction",
        "set_field",
        "finish",
    ]
    read_element = tools[names.index("read_element")]
    schema = getattr(read_element, "args_schema", None)
    schema_fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
    assert "state" not in schema_fields
    assert "element_id" in schema_fields
    assert "Read one HTML element" in _tool_description(read_element)
    read_section = tools[names.index("read_section")]
    read_section_schema = getattr(read_section, "args_schema", None)
    read_section_fields = getattr(read_section_schema, "model_fields", None) or getattr(read_section_schema, "__fields__", {})
    assert "state" not in read_section_fields
    assert "section_id" in read_section_fields
    assert "Read a heading section" in _tool_description(read_section)
    table_extraction = tools[names.index("table_extraction")]
    assert "double quotes" in _tool_description(table_extraction)
    set_field = tools[names.index("set_field")]
    set_field_description = " ".join(_tool_description(set_field).split())
    assert "for each task field exactly once" in set_field_description
    assert "unrelated elements" in set_field_description


def _tool_name(tool):
    return getattr(tool, "name", getattr(tool, "__name__", ""))


def _tool_description(tool):
    return getattr(tool, "description", getattr(tool, "__doc__", "") or "")


def _find_tree_node(nodes, node_id):
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = _find_tree_node(node.get("children", []), node_id)
        if found is not None:
            return found
    return None
