from __future__ import annotations

from types import SimpleNamespace

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_tools import (
    build_tools,
    _finish,
    _overview,
    _paragraph_extraction,
    _read_element,
    _set_field,
    _table_extraction,
)


def _state():
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">联系人：李老师 电话：12345</p>
    <table id="dp-table-1">
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


def test_read_element_returns_text_element():
    result = _read_element(_state(), "dp-p-1")

    assert result["id"] == "dp-p-1"
    assert result["type"] == "TEXT"
    assert "联系人" in result["text"]


def test_read_element_table_returns_header_only():
    result = _read_element(_state(), "dp-table-1")

    assert result["id"] == "dp-table-1"
    assert result["type"] == "TABLE"
    assert result["columns"] == ["姓名", "学院"]
    assert result["header_row_id"] == "dp-tr-1"
    assert result["row_count"] == 2
    assert "rows" not in result


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
        "overview",
        "read_element",
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
    table_extraction = tools[names.index("table_extraction")]
    assert "double quotes" in _tool_description(table_extraction)


def _tool_name(tool):
    return getattr(tool, "name", getattr(tool, "__name__", ""))


def _tool_description(tool):
    return getattr(tool, "description", getattr(tool, "__doc__", "") or "")
