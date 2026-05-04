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
    _update_plan,
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
        broad_plan=SimpleNamespace(summary="测试", plan=["读取名单表", "写入字段"], risks=[]),
        plan_statuses={},
    )


def _large_table_state(row_count: int = 40):
    rows = "\n".join(
        f'<tr id="dp-big-tr-{index}"><td>学生{index}</td><td>学院{index % 3}</td></tr>'
        for index in range(1, row_count + 1)
    )
    html = f"""
    <h2 id="dp-big-h2-1">大表</h2>
    <table id="dp-big-table-1">
      <caption id="dp-big-caption-1">大名单</caption>
      <tr id="dp-big-tr-0"><th>姓名</th><th>学院</th></tr>
      {rows}
    </table>
    """
    state = _state()
    state.document = build_html_document(html)
    return state


def _risky_table_state():
    html = """
    <h2 id="dp-risk-h2-1">作品名单</h2>
    <table id="dp-risk-table-1">
      <caption id="dp-risk-caption-1">作品替代名单</caption>
      <tr id="dp-risk-tr-0"><th>序号</th><th>作品类型</th><th>论文题目</th></tr>
      <tr id="dp-risk-tr-1"><td>1</td><td>学术论文</td><td>论文 A</td></tr>
      <tr id="dp-risk-tr-2"><td>2</td><td></td><td>论文 B</td></tr>
      <tr id="dp-risk-tr-3"><td>3</td><td>学术 论文</td><td>论文 C</td></tr>
      <tr id="dp-risk-tr-4"><td>4</td><td>大学生创新创业项目成果</td><td>项目 D</td></tr>
    </table>
    """
    state = _state()
    state.document = build_html_document(html)
    return state


def _sparse_label_table_state():
    html = """
    <h2 id="dp-dorm-h2-1">文明模范寝室</h2>
    <table id="dp-dorm-table-1">
      <caption id="dp-dorm-caption-1">文明模范寝室</caption>
      <tr id="dp-dorm-tr-0"><th>楼栋</th><th>房间</th><th>模范/文明</th></tr>
      <tr id="dp-dorm-tr-1"><td>18栋</td><td>101</td><td></td></tr>
      <tr id="dp-dorm-tr-2"><td>18栋</td><td>106</td><td>模范寝室</td></tr>
      <tr id="dp-dorm-tr-3"><td>18栋</td><td>212</td><td>文明寝室</td></tr>
      <tr id="dp-dorm-tr-4"><td>18栋</td><td>214</td><td>文明寝室</td></tr>
      <tr id="dp-dorm-tr-5"><td>18栋</td><td>215</td><td></td></tr>
    </table>
    """
    state = _state()
    state.document = build_html_document(html)
    return state


def test_overview_returns_document_tree():
    result = _overview(_state())

    assert result["tree"][0]["id"] == "dp-h2-1"
    assert result["tree"][0]["text"] == "通知"
    table_node = _find_tree_node(result["tree"], "dp-table-1")
    assert table_node is not None
    assert table_node["id"] == "dp-table-1"
    assert table_node["type"] == "TABLE"
    assert table_node["label"] == "学生名单"
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
        '<table-ref id="dp-table-1" label="学生名单" rows="2" header-row-id="dp-tr-1" '
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
        '<table-ref id="dp-table-1" label="学生名单" rows="2" header-row-id="dp-tr-1" columns="姓名 | 学院" />'
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


def test_table_extraction_all_columns_allowed_for_small_tables():
    result = _table_extraction(_state(), "dp-table-1", "SELECT * FROM data")

    assert result["columns"] == ["姓名", "学院"]
    assert [row["row_id"] for row in result["rows"]] == ["dp-tr-2", "dp-tr-3"]
    assert result["rows"][0]["values"] == {"姓名": "张三", "学院": "计算机学院"}


def test_table_extraction_rejects_select_star_for_large_tables():
    result = _table_extraction(_large_table_state(), "dp-big-table-1", "SELECT * FROM data")

    assert result["ok"] is False
    assert result["error"] == "table is too large for unbounded SELECT *"
    assert result["row_count"] == 40
    assert result["column_count"] == 2
    assert "Select only the needed columns" in result["sql_hint"]
    assert "LIMIT 50 OFFSET 0" in result["sql_hint"]


def test_table_extraction_large_tables_allow_select_star_with_bounded_limit():
    result = _table_extraction(_large_table_state(80), "dp-big-table-1", "SELECT * FROM data LIMIT 50 OFFSET 50")

    assert result["columns"] == ["姓名", "学院"]
    assert len(result["rows"]) == 30
    assert result["rows"][0]["values"] == {"姓名": "学生51", "学院": "学院0"}


def test_table_extraction_large_tables_reject_select_star_above_limit():
    result = _table_extraction(_large_table_state(80), "dp-big-table-1", "SELECT * FROM data LIMIT 51")

    assert result["ok"] is False
    assert result["error"] == "table is too large for unbounded SELECT *"
    assert result["max_select_star_limit"] == 50


def test_table_extraction_large_tables_allow_specific_columns_without_truncating_rows():
    result = _table_extraction(_large_table_state(), "dp-big-table-1", 'SELECT "姓名" FROM data')

    assert result["columns"] == ["姓名"]
    assert len(result["rows"]) == 40
    assert result["rows"][0]["values"] == {"姓名": "学生1"}
    assert result["rows"][-1]["values"] == {"姓名": "学生40"}


def test_table_extraction_reports_table_audit_for_empty_cells():
    result = _table_extraction(
        _risky_table_state(),
        "dp-risk-table-1",
        'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
        reason="抽取作品类型为学术论文的论文题目",
    )

    assert result["table_audit"]["blank_cells"]["total_blank_cell_count"] == 1
    assert result["table_audit"]["blank_cells"]["by_column"] == [
        {
            "column": "作品类型",
            "blank_count": 1,
            "blank_row_ids_sample": ["dp-risk-tr-2"],
        }
    ]


def test_table_extraction_reports_query_audit_for_possible_missed_rows():
    result = _table_extraction(
        _risky_table_state(),
        "dp-risk-table-1",
        'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
        reason="抽取作品类型为学术论文的论文题目",
    )

    predicate = result["query_audit"]["predicate_columns"][0]
    assert predicate["blank_count"] == 1
    assert predicate["blank_row_ids_sample"] == ["dp-risk-tr-2"]
    assert predicate["near_match_rows"] == [{"row_id": "dp-risk-tr-3", "value": "学术 论文"}]


def test_table_extraction_query_audit_summarizes_sparse_label_column_without_warning():
    result = _table_extraction(
        _sparse_label_table_state(),
        "dp-dorm-table-1",
        'SELECT "房间" FROM data WHERE "模范/文明" = "文明寝室"',
        reason="抽取文明寝室名称字段，筛选类别为文明寝室的行",
    )

    assert result["query_audit"]["summary"] == (
        "返回 2 行；筛选列“模范/文明”空白 2 行；"
        "非空分布：文明寝室 2，模范寝室 1；输出列“房间”无空值。"
    )
    predicate = result["query_audit"]["predicate_columns"][0]
    assert predicate["column"] == "模范/文明"
    assert predicate["literal"] == "文明寝室"
    assert predicate["blank_count"] == 2
    assert predicate["blank_row_ids_sample"] == ["dp-dorm-tr-1", "dp-dorm-tr-5"]
    assert predicate["non_empty_distribution"] == [
        {"value": "文明寝室", "count": 2},
        {"value": "模范寝室", "count": 1},
    ]


def test_table_extraction_returns_audit_without_status():
    result = _table_extraction(
        _risky_table_state(),
        "dp-risk-table-1",
        'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
        reason="抽取作品类型为学术论文的论文题目",
    )

    assert "query_quality" not in result
    assert "status" not in result["query_audit"]


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


def test_update_plan_records_plan_status_and_action():
    state = _state()

    result = _update_plan(state, 1, "in_progress", reason="开始读取名单表")
    completed = _update_plan(state, 1, "completed", reason="名单表已产生字段证据")

    assert result["ok"] is True
    assert completed["ok"] is True
    assert state.plan_statuses[1]["status"] == "completed"
    assert state.plan_statuses[1]["step"] == "读取名单表"
    assert state.actions[-1]["tool_name"] == "update_plan"
    assert state.actions[-1]["args"] == {
        "plan_index": 1,
        "status": "completed",
        "reason": "名单表已产生字段证据",
    }


def test_update_plan_rejects_starting_later_plan_before_previous_completed():
    state = _state()
    state.broad_plan = SimpleNamespace(
        summary="测试",
        plan=["读取名单表", "确认联系人", "确认字段", "写入字段"],
        risks=[],
    )

    _update_plan(state, 1, "in_progress", reason="开始读取名单表")
    _update_plan(state, 1, "completed", reason="名单表已产生字段证据")
    result = _update_plan(state, 4, "in_progress", reason="跳到写字段")

    assert result["ok"] is False
    assert result["errors"][0]["message"] == "plan_index must advance sequentially"
    assert result["errors"][0]["next_plan_index"] == 2
    assert result["errors"][0]["requested_plan_index"] == 4


def test_update_plan_rejects_completing_plan_that_is_not_in_progress():
    result = _update_plan(_state(), 1, "completed", reason="直接完成")

    assert result["ok"] is False
    assert result["errors"][0]["message"] == "plan must be in_progress before completed"
    assert result["errors"][0]["plan_index"] == 1


def test_update_plan_rejects_invalid_plan_index():
    result = _update_plan(_state(), 99, "completed", reason="不存在")

    assert result["ok"] is False
    assert result["errors"][0]["message"] == "plan_index is outside the broad plan"


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
        "update_plan",
        "read_element",
        "read_section",
        "table_extraction",
        "paragraph_extraction",
        "set_field",
        "finish",
    ]
    update_plan = tools[names.index("update_plan")]
    update_plan_schema = getattr(update_plan, "args_schema", None)
    update_plan_fields = getattr(update_plan_schema, "model_fields", None) or getattr(update_plan_schema, "__fields__", {})
    assert "state" not in update_plan_fields
    assert "plan_index" in update_plan_fields
    assert "status" in update_plan_fields
    assert "Mark one broad-plan step" in _tool_description(update_plan)
    read_element = tools[names.index("read_element")]
    schema = getattr(read_element, "args_schema", None)
    schema_fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
    assert "state" not in schema_fields
    assert "element_id" in schema_fields
    assert "reason" in schema_fields
    assert "Read one HTML element" in _tool_description(read_element)
    read_section = tools[names.index("read_section")]
    read_section_schema = getattr(read_section, "args_schema", None)
    read_section_fields = getattr(read_section_schema, "model_fields", None) or getattr(read_section_schema, "__fields__", {})
    assert "state" not in read_section_fields
    assert "section_id" in read_section_fields
    assert "reason" in read_section_fields
    assert "Read a heading section" in _tool_description(read_section)
    assert "Prefer increasing depth" in _tool_description(read_section)
    assert "many read_element calls" in _tool_description(read_section)
    table_extraction = tools[names.index("table_extraction")]
    table_schema = getattr(table_extraction, "args_schema", None)
    table_fields = getattr(table_schema, "model_fields", None) or getattr(table_schema, "__fields__", {})
    assert "reason" in table_fields
    assert "double quotes" in _tool_description(table_extraction)
    assert "query_audit few-shot" in _tool_description(table_extraction)
    assert "judge blank filter cells from table context" in _tool_description(table_extraction)
    assert "do not say a blank row is normal only because WHERE did not select it" in _tool_description(table_extraction)
    set_field = tools[names.index("set_field")]
    set_field_schema = getattr(set_field, "args_schema", None)
    set_field_fields = getattr(set_field_schema, "model_fields", None) or getattr(set_field_schema, "__fields__", {})
    assert "reason" in set_field_fields
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
