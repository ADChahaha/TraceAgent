from __future__ import annotations

from types import SimpleNamespace
import json

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_tools import (
    build_tools,
    _finish,
    _overview,
    _paragraph_extraction,
    _preview_inline_evidence,
    _read_block_range,
    _query_table,
    _read_blocks,
    _read_element,
    _read_list,
    _read_section,
    _scan_document,
    _search_elements,
    _set_field,
    _table_extraction,
    _update_plan,
)


def _state():
    long_notice = "这是完整通知正文，" + "需要保留全部文字用于模型判断。" * 12
    html = """
    <h2 id="dp-h2-1">通知</h2>
    <p id="dp-p-1">联系人：李老师 电话：12345</p>
    <p id="dp-p-long">{long_notice}</p>
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
    """.format(long_notice=long_notice)
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


def _mixed_outline_state():
    html = """
    <section id="dp-page-1">
      <h1 id="dp-h1-1">合同总则</h1>
      <p id="dp-p-1">前言段落，说明合同背景。</p>
      <table id="dp-table-1">
        <caption id="dp-caption-1">学生名单</caption>
        <tr id="dp-tr-1"><th>姓名</th><th>学院</th></tr>
        <tr id="dp-tr-2"><td>张三</td><td>计算机学院</td></tr>
      </table>
      <p id="dp-p-2">第二段正文，继续说明条款。</p>
      <ul id="dp-ul-1">
        <li id="dp-li-1">第一项</li>
        <li id="dp-li-2">第二项</li>
        <li id="dp-li-3">第三项</li>
      </ul>
      <h2 id="dp-h2-1">1. 定义</h2>
      <p id="dp-p-3">定义条款正文。</p>
    </section>
    """
    return SimpleNamespace(
        document=build_html_document(html),
        task_spec=SimpleNamespace(
            fields=[SimpleNamespace(name="student_name", type="string", required=True)]
        ),
        field_states={},
        actions=[],
        observed_evidence_ids=set(),
        broad_plan=SimpleNamespace(summary="测试", plan=["读取正文"], risks=[]),
        plan_statuses={},
    )


def _list_state():
    state = _state()
    state.task_spec.fields.append(
        SimpleNamespace(name="student_names", type="list[string]", required=True)
    )
    return state


def _mark_list_evidence_observed(state):
    _table_extraction(
        state,
        "dp-table-1",
        "SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
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


def _long_section_state():
    paragraphs = "\n".join(
        f'<p id="dp-long-p-{index}">{"超长章节正文" * 120}</p>'
        for index in range(1, 90)
    )
    html = f"""
    <h2 id="dp-long-h2-1">超长章节</h2>
    {paragraphs}
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


def _many_blank_table_state():
    blank_rows = "\n".join(
        f'<tr id="dp-many-blank-tr-{index}"><td>{index}</td><td></td></tr>'
        for index in range(1, 13)
    )
    html = f"""
    <h2 id="dp-many-blank-h2-1">空值表</h2>
    <table id="dp-many-blank-table-1">
      <tr id="dp-many-blank-tr-0"><th>序号</th><th>标签</th></tr>
      {blank_rows}
      <tr id="dp-many-blank-tr-13"><td>13</td><td>有效</td></tr>
    </table>
    """
    state = _state()
    state.document = build_html_document(html)
    return state


def test_overview_returns_document_tree():
    state = _state()
    result = _overview(state)

    assert result["sections"] == [
        {
            "section_id": "dp-h2-1",
            "title": "通知",
            "level": 2,
            "block_count": 0,
            "subsections": [],
        },
        {
            "section_id": "dp-h3-1",
            "title": "名单",
            "level": 3,
            "block_count": 0,
            "subsections": [],
        },
    ]
    assert "tree" not in result
    assert state.actions[-1]["tool_name"] == "overview"


def test_overview_exposes_mixed_dom_items_in_dom_order():
    state = _mixed_outline_state()
    result = _overview(state)

    items = result["items"]
    assert [item["item_id"] for item in items] == [
        "dp-page-1",
        "dp-h1-1",
        "dp-p-1",
        "dp-table-1",
        "dp-p-2",
        "dp-ul-1",
        "dp-h2-1",
        "dp-p-3",
    ]
    assert items[0]["type"] == "SECTION"
    assert items[0]["tag"] == "section"
    assert items[0]["read_with"] == "read_blocks"
    assert items[0]["parent_section_id"] == ""
    assert items[1]["type"] == "TITLE"
    assert items[1]["read_with"] == "read_section"
    assert items[2]["type"] == "TEXT"
    assert items[2]["read_with"] == "read_blocks"
    assert items[2]["parent_section_id"] == ""
    assert items[2]["preview"] == "前言段落，说明合同背景。"
    assert items[3]["type"] == "TABLE"
    assert items[3]["read_with"] == "query_table"
    assert items[3]["block_offset"] == 0
    assert items[3]["columns"] == ["姓名", "学院"]
    assert items[3]["row_count"] == 1
    assert items[5]["type"] == "LIST"
    assert items[5]["read_with"] == "read_list"
    assert items[5]["block_offset"] == 0
    assert items[5]["item_count"] == 3
    assert items[5]["preview"] == ["第一项", "第二项", "第三项"]
    assert items[6]["type"] == "SECTION_HEADER"
    assert items[6]["read_with"] == "read_section"
    assert items[7]["preview"] == "定义条款正文。"


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
    assert "double quotes" in result["sql_hint"]
    assert "论文题目" not in result["sql_hint"]
    assert "作品类型" not in result["sql_hint"]
    assert "学术论文" not in result["sql_hint"]
    assert result["evidence_ids"] == ["dp-table-1"]
    assert "rows" not in result


def test_read_section_does_not_read_sibling_blocks():
    result = _read_section(_state(), "dp-h2-1")

    assert result["section_id"] == "dp-h2-1"
    assert result["title"] == "通知"
    assert result["blocks"] == []
    assert result["evidence_ids"] == []


def test_read_blocks_reads_leaf_block_by_selected_index():
    state = _state()

    result = _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")

    assert result["section_id"] == "dp-p-1"
    assert result["indexes"] == [0]
    assert [block["offset"] for block in result["blocks"]] == [0]
    assert result["blocks"][0]["html"] == '<text id="dp-p-1">联系人：李老师 电话：12345</text>'
    assert result["evidence_ids"] == ["dp-p-1"]
    assert state.observed_evidence_ids == {"dp-p-1"}
    assert state.actions[-1]["args"]["indexes"] == [0]


def test_read_blocks_returns_list_and_table_refs_without_expanding_rows():
    state = _mixed_outline_state()

    result = _read_blocks(state, "dp-page-1", indexes=[2, 4], reason="查看名单结构")

    assert result["blocks"][0]["html"] == (
        '<table-ref id="dp-table-1" label="学生名单" rows="1" header-row-id="dp-tr-1" columns="姓名 | 学院" />'
    )
    assert result["blocks"][1]["html"].startswith('<list-ref id="dp-ul-1" items="3">')
    assert '<item-ref id="dp-li-1">' in result["blocks"][1]["html"]
    assert result["evidence_ids"] == ["dp-table-1", "dp-ul-1"]


def test_read_blocks_supports_section_scopes_and_leaf_block_ids():
    state = _mixed_outline_state()

    section_scope = _read_blocks(state, "dp-page-1", indexes=[1, 2, 3], reason="读取页面正文")
    assert [block["block_id"] for block in section_scope["blocks"]] == ["dp-p-1", "dp-table-1", "dp-p-2"]
    assert section_scope["blocks"][0]["html"] == '<text id="dp-p-1">前言段落，说明合同背景。</text>'
    assert section_scope["blocks"][1]["html"].startswith('<table-ref id="dp-table-1"')
    assert section_scope["blocks"][2]["html"] == '<text id="dp-p-2">第二段正文，继续说明条款。</text>'
    assert section_scope["evidence_ids"] == ["dp-p-1", "dp-table-1", "dp-p-2"]

    leaf_scope = _read_blocks(state, "dp-p-3", indexes=[0], reason="读取单段正文")
    assert leaf_scope["section_id"] == "dp-p-3"
    assert leaf_scope["indexes"] == [0]
    assert [block["block_id"] for block in leaf_scope["blocks"]] == ["dp-p-3"]
    assert leaf_scope["blocks"][0]["html"] == '<text id="dp-p-3">定义条款正文。</text>'
    assert leaf_scope["evidence_ids"] == ["dp-p-3"]


def test_read_blocks_reads_non_contiguous_selected_indexes():
    state = _mixed_outline_state()

    result = _read_blocks(state, "dp-page-1", indexes=[1, 3], reason="只读取两个非连续正文块")

    assert result["section_id"] == "dp-page-1"
    assert result["indexes"] == [1, 3]
    assert [block["block_id"] for block in result["blocks"]] == ["dp-p-1", "dp-p-2"]
    assert result["evidence_ids"] == ["dp-p-1", "dp-p-2"]
    assert state.actions[-1]["tool_name"] == "read_blocks"
    assert state.actions[-1]["args"]["indexes"] == [1, 3]


def test_read_block_range_reads_contiguous_window():
    state = _mixed_outline_state()

    result = _read_block_range(
        state,
        "dp-page-1",
        start_index=1,
        count=3,
        reason="连续阅读前言、表格和第二段",
    )

    assert result["section_id"] == "dp-page-1"
    assert result["start_index"] == 1
    assert result["count"] == 3
    assert result["indexes"] == [1, 2, 3]
    assert [block["block_id"] for block in result["blocks"]] == ["dp-p-1", "dp-table-1", "dp-p-2"]
    assert result["blocks"][1]["html"].startswith('<table-ref id="dp-table-1"')
    assert result["evidence_ids"] == ["dp-p-1", "dp-table-1", "dp-p-2"]
    assert state.observed_evidence_ids == {"dp-p-1", "dp-table-1", "dp-p-2"}
    assert state.actions[-1]["tool_name"] == "read_block_range"
    assert state.actions[-1]["args"] == {
        "section_id": "dp-page-1",
        "start_index": 1,
        "count": 3,
        "reason": "连续阅读前言、表格和第二段",
    }


def test_read_block_range_rejects_invalid_range_arguments():
    state = _mixed_outline_state()

    bad_start = _read_block_range(state, "dp-page-1", start_index=-1, count=2, reason="负 start")
    bad_count = _read_block_range(state, "dp-page-1", start_index=1, count=0, reason="零 count")
    out_of_range = _read_block_range(state, "dp-page-1", start_index=99, count=2, reason="越界 start")

    assert bad_start == {"ok": False, "error": "start_index must be a non-negative integer"}
    assert bad_count == {"ok": False, "error": "count must be a positive integer"}
    assert out_of_range == {"ok": False, "error": "start_index outside scope: 99", "block_count": 7}
    assert state.actions[-3]["tool_name"] == "read_block_range"
    assert state.actions[-3]["args"]["start_index"] == -1
    assert state.actions[-1]["args"]["start_index"] == 99


def test_read_blocks_rejects_invalid_indexes():
    state = _state()

    empty = _read_blocks(state, "dp-h2-1", indexes=[], reason="空 index")
    negative = _read_blocks(state, "dp-h2-1", indexes=[-1], reason="负 index")
    out_of_range = _read_blocks(state, "dp-h2-1", indexes=[99], reason="越界 index")
    non_integer = _read_blocks(state, "dp-h2-1", indexes=["abc"], reason="非整数 index")

    assert empty == {"ok": False, "error": "indexes must be a non-empty list"}
    assert negative == {"ok": False, "error": "index outside scope: -1", "block_count": 0}
    assert out_of_range == {"ok": False, "error": "index outside scope: 99", "block_count": 0}
    assert non_integer == {"ok": False, "error": "indexes must contain integers"}
    assert state.actions[-4]["args"]["indexes"] == []
    assert state.actions[-1]["args"]["indexes"] == ["abc"]


def test_read_list_paginates_list_items():
    state = _mixed_outline_state()

    result = _read_list(state, "dp-page-1", block_offset=4, item_offset=1, number=2, reason="读取名单列表")

    assert result["section_id"] == "dp-page-1"
    assert result["block_offset"] == 4
    assert result["list_id"] == "dp-ul-1"
    assert [item["item_offset"] for item in result["items"]] == [1, 2]
    assert result["items"][0]["item_id"] == "dp-li-2"
    assert result["items"][0]["html"] == '<item id="dp-li-2">第二项</item>'
    assert result["evidence_ids"] == ["dp-ul-1", "dp-li-2", "dp-li-3"]
    assert state.observed_evidence_ids == {"dp-ul-1", "dp-li-2", "dp-li-3"}


def test_read_list_uses_leaf_list_id_with_zero_offset():
    state = _mixed_outline_state()

    result = _read_list(
        state,
        "dp-ul-1",
        block_offset=0,
        item_offset=1,
        number=2,
        reason="直接读取 overview 暴露的顶层列表 id",
    )

    assert result["section_id"] == "dp-ul-1"
    assert result["block_offset"] == 0
    assert result["list_id"] == "dp-ul-1"
    assert [item["item_id"] for item in result["items"]] == ["dp-li-2", "dp-li-3"]
    assert result["evidence_ids"] == ["dp-ul-1", "dp-li-2", "dp-li-3"]
    assert state.observed_evidence_ids == {"dp-ul-1", "dp-li-2", "dp-li-3"}


def test_search_elements_returns_paragraphs_and_observes_evidence():
    state = _state()

    result = _search_elements(state, "联系人", limit=5, reason="定位联系人字段")

    assert result["query"] == "联系人"
    assert result["match_count"] == 1
    assert result["matches"][0]["element_id"] == "dp-p-1"
    assert result["matches"][0]["type"] == "TEXT"
    assert result["matches"][0]["html"] == '<text id="dp-p-1">联系人：李老师 电话：12345</text>'
    assert result["matches"][0]["evidence_ids"] == ["dp-p-1"]
    assert result["matches"][0]["text_chars"] == len("联系人：李老师 电话：12345")
    assert state.observed_evidence_ids == {"dp-p-1"}
    assert state.actions[-1]["tool_name"] == "search_elements"


def test_search_elements_excludes_page_level_aggregate_text():
    state = _state()
    state.document = build_html_document(
        """
        <p id="page_001">Page 1 联系人：整页聚合文本，不应被 search_elements 返回。</p>
        <p id="p001_b001">联系人：李老师 电话：12345</p>
        <h2 id="p001_h001">联系人安排</h2>
        """
    )

    result = _search_elements(state, "联系人", limit=10, reason="定位联系人字段")

    element_ids = [match["element_id"] for match in result["matches"]]
    assert "page_001" not in element_ids
    assert element_ids == ["p001_b001", "p001_h001"]
    assert state.observed_evidence_ids == {"p001_b001", "p001_h001"}


def test_search_elements_result_can_be_used_as_evidence():
    state = _state()
    _search_elements(state, "联系人", limit=5, reason="定位联系人字段")
    preview = _preview_inline_evidence(
        state,
        "dp-p-1",
        start_index=0,
        count=5,
        reason="把联系人段落细化为字段证据",
    )

    result = _set_field(
        state,
        "contact_phone",
        "12345",
        [preview["inline_evidence"][0]["inline_id"]],
        "resolved",
        None,
    )

    assert result["ok"] is True
    assert state.field_states["contact_phone"]["evidence_ids"] == [
        "dp-p-1::inline-0"
    ]


def test_scan_document_uses_isolated_model_on_scope_without_tools_and_observes_blocks():
    state = _state()
    html = """
        <p id="page_001">Page 1 联系人：整页聚合文本，不应作为证据。</p>
        <section id="p001_sec">
          <h2 id="p001_h001">联系方式</h2>
          <p id="p001_b001">联系人：李老师 电话：12345</p>
          <h3 id="p001_h002">补充联系方式</h3>
          <p id="p001_b002">邮箱：teacher@example.com</p>
        </section>
        <h2 id="p002_h001">其他安排</h2>
        <p id="p002_b001">联系人：王老师 电话：67890</p>
        """
    state.document = build_html_document(html)
    state.extraction_input = SimpleNamespace(html=html)

    class FakeScanModel:
        def __init__(self):
            self.messages = None

        def bind_tools(self, tools, tool_choice=None):
            raise AssertionError("isolated document scan must not bind tools")

        def invoke(self, messages):
            self.messages = messages
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "candidates": [
                            {"element_id": "page_001", "reason": "整页聚合命中"},
                            {"element_id": "missing", "reason": "不存在的 id"},
                            {"element_id": "p002_b001", "reason": "scope 外命中"},
                            {"element_id": "p001_b001", "reason": "联系人和电话在同一段"},
                            {"id": "p001_h002", "reason": "scope 内子标题"},
                        ]
                    },
                    ensure_ascii=False,
                )
            )

    scan_model = FakeScanModel()
    state.document_scan_model = scan_model

    result = _scan_document(state, "p001_sec", "联系人", limit=5, reason="搜索联系人字段")

    assert result["scope_id"] == "p001_sec"
    assert result["query"] == "联系人"
    assert result["candidate_count"] == 2
    assert [candidate["element_id"] for candidate in result["candidates"]] == [
        "p001_b001",
        "p001_h002",
    ]
    assert result["candidates"][0]["html"] == '<text id="p001_b001">联系人：李老师 电话：12345</text>'
    assert result["candidates"][0]["evidence_ids"] == ["p001_b001"]
    assert result["candidates"][0]["selection_basis"] == "联系人和电话在同一段"
    assert "subagent_reason" not in result["candidates"][0]
    assert state.observed_evidence_ids == {"p001_b001", "p001_h002"}
    assert "scan_document" not in scan_model.messages[0].content
    assert "You have no tools" in scan_model.messages[0].content
    assert "Do not judge which candidate supports an answer choice" in scan_model.messages[0].content
    assert "Scope id: p001_sec" in scan_model.messages[-1].content
    assert "Scope HTML" in scan_model.messages[-1].content
    assert '"selection_basis"' in scan_model.messages[-1].content
    assert '"reason"' not in scan_model.messages[-1].content
    assert "联系人：李老师 电话：12345" in scan_model.messages[-1].content
    assert "联系人：王老师 电话：67890" not in scan_model.messages[-1].content
    assert state.actions[-1]["tool_name"] == "scan_document"


def test_scan_document_result_can_be_used_as_evidence():
    state = _state()

    class FakeScanModel:
        def invoke(self, messages):
            return SimpleNamespace(
                content=json.dumps(
                    {"candidates": [{"element_id": "dp-p-1", "reason": "联系人段落"}]},
                    ensure_ascii=False,
                )
            )

    state.document_scan_model = FakeScanModel()
    _scan_document(state, "dp-p-1", "联系人", limit=3, reason="搜索联系人字段")
    preview = _preview_inline_evidence(
        state,
        "dp-p-1",
        start_index=0,
        count=5,
        reason="把 scoped reader 候选细化为字段证据",
    )

    result = _set_field(
        state,
        "contact_phone",
        "12345",
        [preview["inline_evidence"][0]["inline_id"]],
        "resolved",
        None,
    )

    assert result["ok"] is True
    assert state.field_states["contact_phone"]["evidence_ids"] == [
        "dp-p-1::inline-0"
    ]


def test_scan_document_returns_error_without_scan_model():
    result = _scan_document(_state(), "dp-h2-1", "联系人", limit=3, reason="搜索联系人字段")

    assert result["ok"] is False
    assert result["error"] == "document_scan_model is not configured"


def test_scan_document_returns_error_for_unknown_scope_id():
    state = _state()
    state.document_scan_model = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="{}"))

    result = _scan_document(state, "missing", "联系人", limit=3, reason="搜索联系人字段")

    assert result["ok"] is False
    assert result["error"] == "unknown scope id: missing"


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


def test_query_table_uses_section_block_offset_for_sql():
    state = _mixed_outline_state()

    result = _query_table(
        state,
        "dp-page-1",
        block_offset=2,
        sql="SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
        reason="查询表格 block 中的计算机学院学生",
    )

    assert result["section_id"] == "dp-page-1"
    assert result["block_offset"] == 2
    assert result["table_id"] == "dp-table-1"
    assert result["rows"][0]["row_id"] == "dp-tr-2"
    assert result["rows"][0]["values"] == {"姓名": "张三"}
    assert state.actions[-1]["tool_name"] == "query_table"
    assert state.actions[-1]["args"]["section_id"] == "dp-page-1"
    assert state.actions[-1]["args"]["block_offset"] == 2


def test_query_table_uses_leaf_table_id_with_zero_offset():
    state = _mixed_outline_state()

    result = _query_table(
        state,
        "dp-table-1",
        block_offset=0,
        sql="SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
        reason="直接查询 overview 暴露的顶层表格 id",
    )

    assert result["section_id"] == "dp-table-1"
    assert result["block_offset"] == 0
    assert result["table_id"] == "dp-table-1"
    assert result["rows"][0]["row_id"] == "dp-tr-2"
    assert result["rows"][0]["values"] == {"姓名": "张三"}
    assert state.actions[-1]["tool_name"] == "query_table"
    assert state.actions[-1]["args"]["section_id"] == "dp-table-1"
    assert state.actions[-1]["args"]["block_offset"] == 0


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
            "blank_row_ids": ["dp-risk-tr-2"],
        }
    ]


def test_table_extraction_table_audit_keeps_first_ten_blank_row_ids_without_truncated_label():
    result = _table_extraction(
        _many_blank_table_state(),
        "dp-many-blank-table-1",
        'SELECT "序号", "标签" FROM data',
        reason="读取空值表",
    )

    blank_column = result["table_audit"]["blank_cells"]["by_column"][0]
    assert blank_column == {
        "column": "标签",
        "blank_count": 12,
        "blank_row_ids": [
            "dp-many-blank-tr-1",
            "dp-many-blank-tr-2",
            "dp-many-blank-tr-3",
            "dp-many-blank-tr-4",
            "dp-many-blank-tr-5",
            "dp-many-blank-tr-6",
            "dp-many-blank-tr-7",
            "dp-many-blank-tr-8",
            "dp-many-blank-tr-9",
            "dp-many-blank-tr-10",
        ],
    }
    assert "truncated" not in blank_column
    assert "by_column_truncated" not in result["table_audit"]["blank_cells"]


def test_table_extraction_returns_summary_without_query_audit():
    result = _table_extraction(
        _risky_table_state(),
        "dp-risk-table-1",
        'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
        reason="抽取作品类型为学术论文的论文题目",
    )

    assert "query_audit" not in result
    assert result["summary"] == "返回 1 行；输出列“论文题目”空值 0/1 行。"


def test_table_extraction_summary_summarizes_selected_output_empty_cells_without_warning():
    result = _table_extraction(
        _sparse_label_table_state(),
        "dp-dorm-table-1",
        'SELECT "房间" FROM data WHERE "模范/文明" = "文明寝室"',
        reason="抽取文明寝室名称字段，筛选类别为文明寝室的行",
    )

    assert result["summary"] == "返回 2 行；输出列“房间”空值 0/2 行。"
    assert "query_audit" not in result
    assert "非空分布" not in result["summary"]


def test_table_extraction_returns_lightweight_audit_without_status():
    result = _table_extraction(
        _risky_table_state(),
        "dp-risk-table-1",
        'SELECT "论文题目" FROM data WHERE "作品类型" = "学术论文"',
        reason="抽取作品类型为学术论文的论文题目",
    )

    assert "query_quality" not in result
    assert "query_audit" not in result
    assert "status" not in result["table_audit"]


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


def test_preview_inline_evidence_returns_sentence_candidates_and_observes_inline_ids():
    state = _state()
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")

    result = _preview_inline_evidence(
        state,
        "dp-p-1",
        start_index=0,
        count=5,
        reason="准备写联系人电话证据",
    )

    assert result["source_id"] == "dp-p-1"
    assert result["total_inline_count"] == 1
    assert result["inline_evidence"] == [
        {
            "inline_id": "dp-p-1::inline-0",
            "inline_index": 0,
            "source_id": "dp-p-1",
            "text": "联系人：李老师 电话：12345",
            "char_start": 0,
            "char_end": len("联系人：李老师 电话：12345"),
        }
    ]
    assert result["evidence_ids"] == ["dp-p-1::inline-0"]
    assert state.observed_evidence_ids == {"dp-p-1", "dp-p-1::inline-0"}
    assert state.inline_evidence_by_id["dp-p-1::inline-0"]["source_id"] == "dp-p-1"
    assert state.actions[-1]["tool_name"] == "preview_inline_evidence"


def test_preview_inline_evidence_keeps_long_sentence_as_one_inline_candidate():
    state = _state()
    long_sentence = "This definition contains many coordinated legal clauses, " + "additional words " * 45 + "and ends here."
    state.document = build_html_document(
        f'<p id="dp-long-sentence">{long_sentence}</p>'
    )
    _read_blocks(state, "dp-long-sentence", indexes=[0], reason="读取长定义句")

    result = _preview_inline_evidence(
        state,
        "dp-long-sentence",
        start_index=0,
        count=5,
        reason="长句作为一个 inline 证据锚点",
    )

    assert len(long_sentence) > 280
    assert result["total_inline_count"] == 1
    assert result["inline_evidence"][0]["text"] == long_sentence
    assert result["inline_evidence"][0]["inline_id"] == "dp-long-sentence::inline-0"


def test_preview_inline_evidence_requires_observed_text_source():
    state = _state()

    unobserved = _preview_inline_evidence(
        state,
        "dp-p-1",
        start_index=0,
        count=5,
        reason="未先读取段落",
    )
    table = _preview_inline_evidence(
        state,
        "dp-table-1",
        start_index=0,
        count=5,
        reason="表格不能转 inline",
    )

    assert unobserved == {
        "ok": False,
        "error": "source_id must be observed before preview_inline_evidence",
        "source_id": "dp-p-1",
    }
    assert table == {
        "ok": False,
        "error": "source_id must be a text-like element; use query_table for tables and read_list for lists",
        "source_id": "dp-table-1",
    }


def test_set_field_requires_inline_evidence_for_text_blocks():
    state = _state()
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")

    coarse = _set_field(
        state,
        "contact_phone",
        "12345",
        ["dp-p-1"],
        "resolved",
        None,
    )
    preview = _preview_inline_evidence(
        state,
        "dp-p-1",
        start_index=0,
        count=5,
        reason="细化联系人电话证据",
    )
    precise = _set_field(
        state,
        "contact_phone",
        "12345",
        [preview["inline_evidence"][0]["inline_id"]],
        "resolved",
        None,
    )

    assert coarse["ok"] is False
    assert coarse["errors"][0]["message"] == (
        "text evidence must use inline evidence ids from preview_inline_evidence"
    )
    assert coarse["errors"][0]["ids"] == ["dp-p-1"]
    assert precise["ok"] is True
    assert state.field_states["contact_phone"]["evidence_ids"] == [
        "dp-p-1::inline-0"
    ]


def test_set_field_requires_row_or_item_level_evidence_for_tables_and_lists():
    state = _mixed_outline_state()
    _read_blocks(state, "dp-page-1", indexes=[2, 4], reason="读取表格和列表引用")

    table_only = _set_field(
        state,
        "student_name",
        "张三",
        ["dp-table-1"],
        "resolved",
        None,
    )
    list_only = _set_field(
        state,
        "student_name",
        "第一项",
        ["dp-ul-1"],
        "resolved",
        None,
    )
    table_rows = _query_table(
        state,
        "dp-table-1",
        block_offset=0,
        sql="SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
        reason="读取表格行",
    )
    table_precise = _set_field(
        state,
        "student_name",
        "张三",
        table_rows["rows"][0]["evidence_ids"],
        "resolved",
        None,
    )
    list_items = _read_list(
        state,
        "dp-ul-1",
        block_offset=0,
        item_offset=0,
        number=1,
        reason="读取列表项",
    )
    list_precise = _set_field(
        state,
        "student_name",
        "第一项",
        list_items["evidence_ids"],
        "resolved",
        None,
    )

    assert table_only["ok"] is False
    assert table_only["errors"][0]["message"] == "table evidence must include row ids from query_table"
    assert table_only["errors"][0]["ids"] == ["dp-table-1"]
    assert list_only["ok"] is False
    assert list_only["errors"][0]["message"] == "list evidence must include item ids from read_list"
    assert list_only["errors"][0]["ids"] == ["dp-ul-1"]
    assert table_precise["ok"] is True
    assert list_precise["ok"] is True


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
    assert "论文题目" not in result["sql_hint"]
    assert "作品类型" not in result["sql_hint"]
    assert "学术论文" not in result["sql_hint"]


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


def test_set_field_rejects_value_that_does_not_match_field_type():
    state = _list_state()
    _mark_list_evidence_observed(state)

    result = _set_field(
        state,
        "student_names",
        "张三",
        ["dp-table-1", "dp-tr-2"],
        "resolved",
        None,
    )

    assert result == {
        "ok": False,
        "errors": [
            {
                "field": "student_names",
                "message": "field value does not match type",
                "expected_type": "list[string]",
            }
        ],
    }
    assert "student_names" not in state.field_states


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
        "overview",
        "read_section",
        "read_blocks",
        "read_block_range",
        "read_list",
        "query_table",
        "preview_inline_evidence",
        "set_field",
        "finish",
    ]
    update_plan = tools[names.index("update_plan")]
    update_schema = getattr(update_plan, "args_schema", None)
    update_fields = getattr(update_schema, "model_fields", None) or getattr(update_schema, "__fields__", {})
    assert "state" not in update_fields
    assert "plan_index" in update_fields
    assert "status" in update_fields
    overview = tools[names.index("overview")]
    overview_description = _tool_description(overview)
    assert "section headers" in overview_description
    assert "same-level block items" in overview_description
    read_section = tools[names.index("read_section")]
    read_section_schema = getattr(read_section, "args_schema", None)
    read_section_fields = getattr(read_section_schema, "model_fields", None) or getattr(read_section_schema, "__fields__", {})
    assert "state" not in read_section_fields
    assert "section_id" in read_section_fields
    assert "reason" in read_section_fields
    assert "actual DOM descendants" in _tool_description(read_section)
    read_blocks = tools[names.index("read_blocks")]
    blocks_schema = getattr(read_blocks, "args_schema", None)
    blocks_fields = getattr(blocks_schema, "model_fields", None) or getattr(blocks_schema, "__fields__", {})
    assert "indexes" in blocks_fields
    assert "offset" not in blocks_fields
    assert "number" not in blocks_fields
    blocks_description = _tool_description(read_blocks)
    assert "section container, heading, or leaf block id" in blocks_description
    assert "selected block indexes" in blocks_description
    assert "not following siblings" in blocks_description
    assert "leaf block id" in blocks_description
    read_block_range = tools[names.index("read_block_range")]
    range_schema = getattr(read_block_range, "args_schema", None)
    range_fields = getattr(range_schema, "model_fields", None) or getattr(range_schema, "__fields__", {})
    assert "start_index" in range_fields
    assert "count" in range_fields
    assert "indexes" not in range_fields
    range_description = _tool_description(read_block_range)
    assert "contiguous range" in range_description
    assert "Use read_blocks" in range_description
    read_list = tools[names.index("read_list")]
    list_schema = getattr(read_list, "args_schema", None)
    list_fields = getattr(list_schema, "model_fields", None) or getattr(list_schema, "__fields__", {})
    assert "item_offset" in list_fields
    list_description = _tool_description(read_list)
    assert "Read list items" in list_description
    assert "top-level list id" in list_description
    assert "block_offset=0" in list_description
    query_table = tools[names.index("query_table")]
    table_schema = getattr(query_table, "args_schema", None)
    table_fields = getattr(table_schema, "model_fields", None) or getattr(table_schema, "__fields__", {})
    assert "block_offset" in table_fields
    assert "sql" in table_fields
    query_table_description = _tool_description(query_table)
    assert "top-level table id" in query_table_description
    assert "block_offset=0" in query_table_description
    assert "double quotes" in query_table_description
    preview_inline = tools[names.index("preview_inline_evidence")]
    preview_schema = getattr(preview_inline, "args_schema", None)
    preview_fields = getattr(preview_schema, "model_fields", None) or getattr(preview_schema, "__fields__", {})
    assert "source_id" in preview_fields
    assert "start_index" in preview_fields
    assert "count" in preview_fields
    preview_description = _tool_description(preview_inline)
    assert "Only use this after reading a text block" in preview_description
    assert "inline_id" in preview_description
    assert "set_field" in preview_description
    set_field = tools[names.index("set_field")]
    set_field_schema = getattr(set_field, "args_schema", None)
    set_field_fields = getattr(set_field_schema, "model_fields", None) or getattr(set_field_schema, "__fields__", {})
    assert "reason" in set_field_fields
    set_field_description = " ".join(_tool_description(set_field).split())
    assert "for each task field exactly once" in set_field_description
    assert "unrelated elements" in set_field_description
    assert "read_blocks" in set_field_description
    assert "read_block_range" in set_field_description
    assert "preview_inline_evidence" in set_field_description
    assert "inline ids" in set_field_description
    assert "row ids" in set_field_description
    assert "item ids" in set_field_description
    assert "query_table" in set_field_description


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
