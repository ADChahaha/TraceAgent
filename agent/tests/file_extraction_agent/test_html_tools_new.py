from __future__ import annotations

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    _anchors,
    _bind_evidence,
    _query_table,
    _read,
    _review_field,
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
        "bind_evidence",
        "review_field",
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


def test_bind_evidence_accumulates_selectors_and_write_field_submits_value():
    state = _state()
    paths = _paths(state)

    first = _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        reason="看到 S001 写明公司成立年份，先绑定证据。",
    )
    second = _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S002"]}],
        reason="看到 S002 写明总部位置，追加同字段证据。",
    )
    _review_field(state, "founded_year", reason="复看候选证据后提交字段值。")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="证据已绑定，提交成立年份。",
    )
    overwritten = _write_field(
        state,
        "founded_year",
        2021,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="覆盖上一版字段值。",
    )
    bad = _bind_evidence(
        state,
        "deposit",
        [{"path": paths["table"], "sentences": ["S001"]}],
        reason="错误地用句子引用表格。",
    )

    assert first["ok"] is True
    assert first["evidence_texts"] == [
        {
            "path": paths["paragraph"],
            "selector": "S001",
            "text": "公司成立于2020年。",
        }
    ]
    assert second["evidence"] == [
        {"path": paths["paragraph"], "sentences": ["S001"]},
        {"path": paths["paragraph"], "sentences": ["S002"]},
    ]
    assert written["field"]["value"] == 2020
    assert written["field"]["evidence"][0]["sentences"] == ["S001"]
    assert overwritten["field"]["value"] == 2021
    assert state.field_states["founded_year"]["value"] == 2021
    assert state.evidence_states["founded_year"]["evidence"][1]["sentences"] == ["S002"]
    assert bad["ok"] is False
    assert "rows" in bad["errors"][0]["message"]
    assert state.events[-1]["type"] == "tool_failed"


def test_write_field_requires_review_and_filters_final_evidence():
    state = _state()
    paths = _paths(state)
    _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        reason="看到 S001 写明公司成立年份，先绑定证据。",
    )
    _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S002"]}],
        reason="看到 S002 写明总部位置，也先绑定为候选。",
    )

    blocked = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="还没复看候选证据，应该被拒绝。",
    )
    _review_field(
        state,
        "founded_year",
        reason="复看候选证据，只保留直接支持成立年份的 S001。",
    )
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="复看后只提交 S001 作为最终证据。",
    )
    bad = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["table"], "rows": ["R001"]}],
        status="resolved",
        reason="不能使用未绑定到该字段的证据。",
    )

    assert blocked["ok"] is False
    assert blocked["errors"][0]["code"] == "REVIEW_REQUIRED"
    assert written["ok"] is True
    assert written["field"]["evidence"] == [{"path": paths["paragraph"], "sentences": ["S001"]}]
    assert written["field"]["evidence_texts"] == [
        {
            "path": paths["paragraph"],
            "selector": "S001",
            "text": "公司成立于2020年。",
        }
    ]
    assert bad["ok"] is False
    assert bad["errors"][0]["code"] == "UNBOUND_FINAL_EVIDENCE"


def test_write_field_without_candidate_evidence_does_not_require_review():
    state = _state()

    written = _write_field(
        state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
        reason="没有候选证据时直接标记缺失。",
    )

    assert written["ok"] is True
    assert written["field"]["evidence"] == []
    assert written["field"]["evidence_texts"] == []


def test_review_field_returns_current_value_description_and_bound_evidence():
    state = _state()
    paths = _paths(state)
    _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        reason="看到 S001 写明公司成立年份，先绑定证据。",
    )
    _review_field(state, "founded_year", reason="复看候选证据后提交字段值。")
    _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="证据已绑定，提交成立年份。",
    )

    result = _review_field(
        state,
        "founded_year",
        reason="重新查看已绑定证据是否直接支持成立年份。",
    )
    missing = _review_field(state, "unknown", reason="查看未知字段。")

    assert result["ok"] is True
    assert result["field_id"] == "founded_year"
    assert result["field"]["value"] == 2020
    assert result["field_description"] == ""
    assert result["evidence_texts"] == [
        {
            "path": paths["paragraph"],
            "selector": "S001",
            "text": "公司成立于2020年。",
        }
    ]
    assert result["guidance"] == (
        "This tool does not judge correctness. Re-read the field description, current value, "
        "and bound evidence, then decide whether to keep the value, overwrite it with write_field, "
        "or bind additional evidence."
    )
    assert state.events[-1]["tool"] == "review_field"
    assert missing["ok"] is False
    assert missing["errors"][0]["code"] == "UNKNOWN_FIELD"


def test_submit_result_validates_required_fields_and_returns_new_field_shape():
    state = _state()
    paths = _paths(state)
    _bind_evidence(
        state,
        "founded_year",
        [{"path": paths["paragraph"], "sentences": ["S001"]}],
        reason="先绑定成立年份证据。",
    )
    _review_field(state, "founded_year", reason="复看成立年份证据。")
    _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="写入成立年份。",
    )
    _bind_evidence(
        state,
        "service_items",
        [{"path": paths["list"], "items": ["I001", "I002"]}],
        reason="先绑定服务列表证据。",
    )
    _review_field(state, "service_items", reason="复看服务列表证据。")
    _write_field(
        state,
        "service_items",
        ["提供系统维护", "提供数据备份"],
        final_evidence=[{"path": paths["list"], "items": ["I001", "I002"]}],
        status="resolved",
        reason="写入服务列表。",
    )
    _bind_evidence(
        state,
        "deposit",
        [{"path": paths["table"], "rows": ["R002"]}],
        reason="先绑定押金证据。",
    )
    _review_field(state, "deposit", reason="复看押金证据。")
    _write_field(
        state,
        "deposit",
        500,
        final_evidence=[{"path": paths["table"], "rows": ["R002"]}],
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
        final_evidence=[],
        status="missing",
        reason="文档未提及该字段。",
    )
    completed = _submit_result(state, reason="字段都已处理，提交最终结果。")

    assert completed["ok"] is False
    assert completed["errors"][0]["code"] == "REQUIRED_MISSING"

    _bind_evidence(
        state,
        "missing_required",
        [{"path": paths["paragraph"], "sentences": ["S002"]}],
        reason="先绑定补齐字段证据。",
    )
    _review_field(state, "missing_required", reason="复看补齐字段证据。")
    _write_field(
        state,
        "missing_required",
        "已补齐",
        final_evidence=[{"path": paths["paragraph"], "sentences": ["S002"]}],
        status="resolved",
        reason="S002 提供补齐字段的测试证据。",
    )
    completed = _submit_result(state, reason="再次提交最终结果。")

    assert completed["ok"] is True
    assert completed["result"]["fields"][0]["field_id"] == "founded_year"
    assert completed["result"]["fields"][0]["evidence"][0]["sentences"] == ["S001"]
    assert state.events[-1]["type"] == "result_completed"
