from __future__ import annotations

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    _anchors,
    _query_table,
    _read,
    _submit_result,
    _tree,
    _write_field,
    build_tools,
)
from service.file_extraction_agent.input_adapter import build_graph_input


def _state():
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "company.html",
                "html": """
                <h1 id="title">公司资料</h1>
                <h2 id="summary">概况</h2>
                <p id="p1">公司成立于2020年。总部位于上海。</p>
                <ul id="list1">
                  <li id="li1">提供系统维护</li>
                  <li id="li2">提供数据备份</li>
                </ul>
                <table id="table1">
                  <caption id="cap1">费用明细</caption>
                  <tr id="tr0"><th>项目</th><th>金额</th></tr>
                  <tr id="tr1"><td>服务费</td><td>1000</td></tr>
                  <tr id="tr2"><td>押金</td><td>500</td></tr>
                </table>
                """,
            }
        ],
        task_spec={
            "fields": [
                {"name": "founded_year", "type": "number", "required": True},
                {"name": "service_items", "type": "list[string]", "required": False},
                {"name": "deposit", "type": "number", "required": False},
                {"name": "missing_required", "type": "string", "required": True},
            ]
        },
    )
    return build_graph_state(extraction_input)


def _paths(state):
    return {
        "paragraph": "/001-company-公司资料/001-概况/001-公司成立于2020年。总部位于上海.md",
        "list": "/001-company-公司资料/001-概况/002-提供系统维护.list",
        "table": "/001-company-公司资料/001-概况/003-费用明细.table",
    }


def test_build_tools_exposes_virtual_tree_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "tree",
        "read",
        "anchors",
        "query_table",
        "write_field",
        "submit_result",
    ]


def test_tree_read_anchors_and_query_record_reasoned_events():
    state = _state()
    paths = _paths(state)

    tree_result = _tree(state, "/", depth=2, reason="先查看输入文档。")
    read_result = _read(state, paths["table"], offset=0, limit=1, reason="读取费用表。")
    anchors_result = _anchors(state, paths["paragraph"], reason="定位成立年份句子。")
    query_result = _query_table(
        state,
        paths["table"],
        'SELECT "项目", "金额" FROM data WHERE "项目" = \'押金\'',
        offset=0,
        limit=10,
        reason="查询押金行。",
    )

    assert "001-company-公司资料/" in tree_result["text"]
    assert "| R001 | 服务费 | 1000 |" in read_result["text"]
    assert anchors_result["anchors"][0]["id"] == "S001"
    assert "| R002 | 押金 | 500 |" in query_result["text"]
    assert [event["type"] for event in state.events] == [
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
    ]
    assert state.events[0]["reason"] == "先查看输入文档。"


def test_write_field_overwrites_result_buffer_and_validates_selectors():
    state = _state()
    paths = _paths(state)

    first = _write_field(
        state,
        "founded_year",
        2020,
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="S001 写明公司成立于2020年。",
    )
    second = _write_field(
        state,
        "founded_year",
        2021,
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="覆盖上一版字段值。",
    )
    bad = _write_field(
        state,
        "deposit",
        500,
        [{"path": paths["table"], "sentences": ["S001"]}],
        status="resolved",
        reason="错误地用句子引用表格。",
    )

    assert first["ok"] is True
    assert first["field"]["evidence_texts"] == [
        {
            "path": paths["paragraph"],
            "selector": "S001",
            "text": "公司成立于2020年。",
        }
    ]
    assert second["field"]["value"] == 2021
    assert state.field_states["founded_year"]["value"] == 2021
    assert bad["ok"] is False
    assert "rows" in bad["errors"][0]["message"]
    assert state.events[-1]["type"] == "tool_failed"


def test_submit_result_validates_required_fields_and_returns_new_field_shape():
    state = _state()
    paths = _paths(state)
    _write_field(
        state,
        "founded_year",
        2020,
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="写入成立年份。",
    )
    _write_field(
        state,
        "service_items",
        ["提供系统维护", "提供数据备份"],
        [{"path": paths["list"], "items": ["I001", "I002"]}],
        status="resolved",
        reason="写入服务列表。",
    )
    _write_field(
        state,
        "deposit",
        500,
        [{"path": paths["table"], "rows": ["R002"]}],
        status="resolved",
        reason="写入押金金额。",
    )

    failed = _submit_result(state, reason="先提交检查必填字段。")
    assert failed["ok"] is False
    assert failed["errors"][0]["field_id"] == "missing_required"

    _write_field(
        state,
        "missing_required",
        None,
        [],
        status="missing",
        reason="文档未提及该字段。",
    )
    completed = _submit_result(state, reason="字段都已处理，提交最终结果。")

    assert completed["ok"] is False
    assert completed["errors"][0]["code"] == "REQUIRED_MISSING"

    _write_field(
        state,
        "missing_required",
        "已补齐",
        [{"path": paths["paragraph"], "sentences": ["S002"]}],
        status="resolved",
        reason="S002 提供补齐字段的测试证据。",
    )
    completed = _submit_result(state, reason="再次提交最终结果。")

    assert completed["ok"] is True
    assert completed["result"]["fields"][0]["field_id"] == "founded_year"
    assert completed["result"]["fields"][0]["evidence"][0]["sentences"] == ["S001"]
    assert state.events[-1]["type"] == "result_completed"
