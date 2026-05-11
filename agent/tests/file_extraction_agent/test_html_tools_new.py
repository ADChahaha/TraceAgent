from __future__ import annotations

from types import SimpleNamespace
import json

from langchain_core.utils.function_calling import convert_to_openai_tool

from service.file_extraction_agent.impl.html_index import build_html_document
from service.file_extraction_agent.impl.html_tools import (
    build_tools,
    _append_stage_progress,
    _complete_stage,
    _finish,
    _overview,
    _paragraph_extraction,
    _preview_inline_evidence,
    _record_stage_evidence,
    _read_block_range,
    _query_table,
    _read_blocks,
    _read_element,
    _read_list,
    _read_section,
    _review_stage_evidence,
    _scan_document,
    _search_elements,
    _set_field,
    _start_stage,
    _table_extraction,
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
        reading_stages=[],
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
        reading_stages=[],
    )


def _section_container_state():
    html = """
    <section id="dp-section-1">
      <h2 id="dp-h2-1">1. 保密信息</h2>
      <p id="dp-p-1">1.1 保密信息包括书面、口头和电子形式披露的信息。</p>
      <p id="dp-p-2">1.2 接收方只能为评估交易目的使用保密信息。</p>
    </section>
    <p id="dp-p-outside">这个平级段落不属于前面的 section。</p>
    """
    return SimpleNamespace(
        document=build_html_document(html),
        task_spec=SimpleNamespace(
            fields=[SimpleNamespace(name="student_name", type="string", required=True)]
        ),
        field_states={},
        actions=[],
        observed_evidence_ids=set(),
        reading_stages=[],
    )


def _list_state():
    state = _state()
    state.task_spec.fields.append(
        SimpleNamespace(name="student_names", type="list[string]", required=True)
    )
    return state


def _enum_state():
    state = _state()
    state.task_spec.fields = [
        SimpleNamespace(
            name="answer",
            type="enum",
            required=True,
            variants=[
                SimpleNamespace(name="text", type="string"),
                SimpleNamespace(name="score", type="number"),
                SimpleNamespace(name="flag", type="boolean"),
                SimpleNamespace(name="labels", type="list[string]"),
                SimpleNamespace(name="amounts", type="list[number]"),
                SimpleNamespace(name="missing", type="null"),
            ],
        )
    ]
    return state


def _mark_list_evidence_observed(state):
    _table_extraction(
        state,
        "dp-table-1",
        "SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
    )


def _start_conclude_stage(state, summary: str = "证据已经读完，可以写字段。") -> str:
    stage_id = _start_stage(
        state,
        "整理已读证据",
        "复核已观察证据并写字段",
        "测试需要进入字段写入阶段。",
    )["stage"]["stage_id"]
    _append_stage_progress(state, stage_id, "investigate", summary)
    return stage_id


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
    result = _overview(state, reason="查看测试文档结构")

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
    result = _overview(state, reason="查看混排 DOM outline")

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


def test_overview_uses_section_container_reader_for_heading_with_container_blocks():
    state = _section_container_state()

    result = _overview(state, reason="定位有真实 section 容器的标题")

    section_item = next(item for item in result["items"] if item["item_id"] == "dp-section-1")
    heading_item = next(item for item in result["items"] if item["item_id"] == "dp-h2-1")
    assert section_item["type"] == "SECTION"
    assert section_item["read_with"] == "read_blocks"
    assert section_item["block_count"] == 3
    assert section_item["valid_indexes"] == [0, 1, 2]
    assert section_item["read_args"] == {"section_id": "dp-section-1", "indexes": [0, 1, 2]}
    assert heading_item["type"] == "SECTION_HEADER"
    assert heading_item["read_with"] == "read_blocks"
    assert heading_item["direct_block_count"] == 0
    assert heading_item["container_id"] == "dp-section-1"
    assert heading_item["container_block_count"] == 3
    assert heading_item["valid_indexes"] == [0, 1, 2]
    assert heading_item["read_args"] == {"section_id": "dp-section-1", "indexes": [0, 1, 2]}


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
    result = _read_section(_state(), "dp-h2-1", reason="确认 heading 不读取平级块")

    assert result["section_id"] == "dp-h2-1"
    assert result["title"] == "通知"
    assert result["direct_block_count"] == 0
    assert result["blocks"] == []
    assert result["evidence_ids"] == []


def test_read_section_reports_container_read_path_when_heading_has_section_parent():
    state = _section_container_state()

    result = _read_section(state, "dp-h2-1", reason="查看标题关联的 section 容器")

    assert result["section_id"] == "dp-h2-1"
    assert result["title"] == "1. 保密信息"
    assert result["direct_block_count"] == 0
    assert result["blocks"] == []
    assert result["container"] == {
        "section_id": "dp-section-1",
        "block_count": 3,
        "valid_indexes": [0, 1, 2],
        "read_with": "read_blocks",
        "read_args": {"section_id": "dp-section-1", "indexes": [0, 1, 2]},
        "blocks": [
            {
                "offset": 0,
                "block_id": "dp-h2-1",
                "type": "SECTION_HEADER",
                "preview": "1.",
            },
            {
                "offset": 1,
                "block_id": "dp-p-1",
                "type": "TEXT",
                "preview": "1.1 保密信息包括书面、口头和电子形式披露的信息。",
            },
            {
                "offset": 2,
                "block_id": "dp-p-2",
                "type": "TEXT",
                "preview": "1.2 接收方只能为评估交易目的使用保密信息。",
            },
        ],
    }
    assert "dp-p-outside" not in json.dumps(result, ensure_ascii=False)


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
    stage_id = _start_conclude_stage(state)

    result = _set_field(
        state,
        "contact_phone",
        "12345",
        [preview["inline_evidence"][0]["inline_id"]],
        "resolved",
        None,
        stage_id=stage_id,
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
    stage_id = _start_conclude_stage(state)

    result = _set_field(
        state,
        "contact_phone",
        "12345",
        [preview["inline_evidence"][0]["inline_id"]],
        "resolved",
        None,
        stage_id=stage_id,
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
    stage_id = _start_conclude_stage(state)
    set_result = _set_field(
        state,
        "student_name",
        row["values"]["姓名"],
        row["evidence_ids"],
        "resolved",
        None,
        stage_id=stage_id,
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


def test_preview_inline_evidence_keeps_semicolon_clauses_in_sentence_candidate():
    state = _state()
    text = (
        "Company shall not use Confidential Information except for evaluation; "
        "provided, however, Confidential Information shall not include public information; "
        "and Recipient shall return materials upon request."
    )
    state.document = build_html_document(f'<p id="dp-semicolon">{text}</p>')
    _read_blocks(state, "dp-semicolon", indexes=[0], reason="读取分号法律句")

    result = _preview_inline_evidence(
        state,
        "dp-semicolon",
        start_index=0,
        count=5,
        reason="分号法律句作为一个 inline 证据锚点",
    )

    assert result["total_inline_count"] == 1
    assert [item["text"] for item in result["inline_evidence"]] == [
        text,
    ]
    assert [item["inline_id"] for item in result["inline_evidence"]] == [
        "dp-semicolon::inline-0",
    ]


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
    stage_id = _start_conclude_stage(state)

    coarse = _set_field(
        state,
        "contact_phone",
        "12345",
        ["dp-p-1"],
        "resolved",
        None,
        stage_id=stage_id,
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
        stage_id=stage_id,
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
    stage_id = _start_conclude_stage(state)

    table_only = _set_field(
        state,
        "student_name",
        "张三",
        ["dp-table-1"],
        "resolved",
        None,
        stage_id=stage_id,
    )
    list_only = _set_field(
        state,
        "student_name",
        "第一项",
        ["dp-ul-1"],
        "resolved",
        None,
        stage_id=stage_id,
    )
    table_rows = _query_table(
        state,
        "dp-table-1",
        block_offset=0,
        sql="SELECT 姓名 FROM data WHERE 学院 = '计算机学院'",
        reason="读取表格行",
    )
    list_items = _read_list(
        state,
        "dp-ul-1",
        block_offset=0,
        item_offset=0,
        number=1,
        reason="读取列表项",
    )
    table_precise = _set_field(
        state,
        "student_name",
        "张三",
        table_rows["rows"][0]["evidence_ids"],
        "resolved",
        None,
        stage_id=stage_id,
    )
    list_precise = _set_field(
        state,
        "student_name",
        "第一项",
        list_items["evidence_ids"],
        "resolved",
        None,
        stage_id=stage_id,
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
    stage_id = _start_conclude_stage(state)

    set_result = _set_field(
        state,
        "student_name",
        "张三",
        ["dp-table-1", "dp-tr-2"],
        "resolved",
        None,
        stage_id=stage_id,
    )
    finish_result = _finish(state)

    assert set_result["ok"] is True
    assert state.field_states["student_name"]["value"] == "张三"
    assert finish_result == {"ok": True, "errors": []}


def test_set_field_rejects_value_that_does_not_match_field_type():
    state = _list_state()
    _mark_list_evidence_observed(state)
    stage_id = _start_conclude_stage(state)

    result = _set_field(
        state,
        "student_names",
        "张三",
        ["dp-table-1", "dp-tr-2"],
        "resolved",
        None,
        stage_id=stage_id,
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


def test_set_field_accepts_tagged_enum_payloads_and_rejects_invalid_variant_values():
    state = _enum_state()
    _read_blocks(state, "dp-p-1", [0], reason="读取联系人")
    inline = _preview_inline_evidence(state, "dp-p-1", 0, 1, reason="细化证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    stage_id = _start_conclude_stage(state)

    bad_variant = _set_field(
        state,
        "answer",
        {"variant": "unknown", "value": "联系人：李老师 电话：12345"},
        [inline_id],
        "resolved",
        None,
        reason="未知 enum variant",
        stage_id=stage_id,
    )
    bad_payload = _set_field(
        state,
        "answer",
        {"variant": "score", "value": "1"},
        [inline_id],
        "resolved",
        None,
        reason="payload 类型错误",
        stage_id=stage_id,
    )
    ok = _set_field(
        state,
        "answer",
        {"variant": "text", "value": "联系人：李老师 电话：12345"},
        [inline_id],
        "resolved",
        None,
        reason="按 text variant 写入",
        stage_id=stage_id,
    )

    assert bad_variant["ok"] is False
    assert bad_variant["errors"][0]["expected_type"] == "enum"
    assert bad_payload["ok"] is False
    assert bad_payload["errors"][0]["expected_type"] == "number"
    assert ok["ok"] is True
    assert state.field_states["answer"]["value"]["variant"] == "text"


def test_finish_allows_resolved_null_enum_variant_without_evidence():
    state = _enum_state()
    stage_id = _start_conclude_stage(state)

    missing_payload = _set_field(
        state,
        "answer",
        {"variant": "missing"},
        [],
        "resolved",
        None,
        reason="缺少显式 value",
        stage_id=stage_id,
    )
    set_result = _set_field(
        state,
        "answer",
        {"variant": "missing", "value": None},
        [],
        "resolved",
        None,
        reason="该字段显式选择 null variant",
        stage_id=stage_id,
    )
    finish_result = _finish(state)

    assert missing_payload["ok"] is False
    assert missing_payload["errors"][0]["expected_type"] == "enum"
    assert set_result["ok"] is True
    assert finish_result == {"ok": True, "errors": []}


def test_finish_still_requires_evidence_for_non_null_enum_variant():
    state = _enum_state()
    stage_id = _start_conclude_stage(state)

    set_result = _set_field(
        state,
        "answer",
        {"variant": "flag", "value": True},
        [],
        "resolved",
        None,
        reason="非 null variant 仍需要证据",
        stage_id=stage_id,
    )
    finish_result = _finish(state)

    assert set_result["ok"] is True
    assert finish_result["ok"] is False
    assert finish_result["errors"] == [
        {"field": "answer", "message": "resolved field requires evidence"}
    ]


def test_start_stage_appends_reading_stage_and_action():
    state = _state()

    result = _start_stage(
        state,
        title="理解通知对象",
        focus="先看通知正文和名单附近内容",
        basis="学生姓名和联系方式可能来自同一处通知正文。",
    )

    assert result["ok"] is True
    assert result["stage"]["stage_id"] == "stage-1"
    assert result["stage"]["status"] == "in_progress"
    assert result["stage"]["title"] == "理解通知对象"
    assert result["stage"]["focus"] == "先看通知正文和名单附近内容"
    assert result["stage"]["basis"] == "学生姓名和联系方式可能来自同一处通知正文。"
    assert result["stage"]["progress"] == []
    assert result["stage"]["evidence_notes"] == []
    assert state.reading_stages == [result["stage"]]
    assert state.actions[-1]["tool_name"] == "start_stage"


def test_start_stage_rejects_new_stage_while_current_stage_is_in_progress():
    state = _state()
    first = _start_stage(state, "理解通知对象", "先看通知正文", "联系人字段需要正文证据。")

    second = _start_stage(state, "理解名单", "继续看名单", "名单可能给出姓名。")
    _append_stage_progress(state, first["stage"]["stage_id"], "investigate", "测试完成当前阶段前已有阅读进展。")
    completed = _complete_stage(
        state,
        first["stage"]["stage_id"],
        "通知对象已经理解。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [],
                "status": "failed",
                "failure_reason": "测试关闭 stage。",
                "rationale": "测试只需要完成当前 stage 以允许开启下一阶段。",
            }
        ],
    )
    third = _start_stage(state, "理解名单", "继续看名单", "名单可能给出姓名。")

    assert second["ok"] is False
    assert second["errors"][0]["message"] == "complete current stage before starting a new stage"
    assert second["errors"][0]["active_stage_id"] == "stage-1"
    assert len(state.reading_stages) == 2
    assert completed["ok"] is True
    assert third["ok"] is True
    assert third["stage"]["stage_id"] == "stage-2"


def test_append_stage_progress_and_complete_stage_are_append_only():
    state = _state()
    stage_id = _start_stage(state, "理解名单来源", "看名单和联系人附近内容", "这些内容可能共享证据。")["stage"][
        "stage_id"
    ]

    progress = _append_stage_progress(
        state,
        stage_id,
        "investigate",
        "读取名单前后的正文，确认名单表是否是目标来源。",
    )
    completed = _complete_stage(
        state,
        stage_id,
        "名单表可作为学生姓名来源，联系人需要另看正文。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [],
                "status": "failed",
                "failure_reason": "测试关闭 stage。",
                "rationale": "测试只检查 stage 完成动作的 append-only 行为。",
            }
        ],
    )

    stage = state.reading_stages[0]
    assert progress["ok"] is True
    assert progress["progress"]["event_id"] == "stage-1-progress-1"
    assert stage["progress"][0]["type"] == "investigate"
    assert completed["ok"] is True
    assert stage["status"] == "completed"
    assert stage["finding"] == "名单表可作为学生姓名来源，联系人需要另看正文。"
    assert stage["progress"] == [progress["progress"]]
    assert "progress" not in completed
    assert state.actions[-2]["tool_name"] == "append_stage_progress"
    assert state.actions[-1]["tool_name"] == "complete_stage"


def test_append_stage_progress_rejects_unknown_stage_or_type_without_mutation():
    state = _state()
    stage_id = _start_stage(state, "理解名单来源", "看名单附近内容", "名单可能给出字段证据。")["stage"][
        "stage_id"
    ]

    bad_stage = _append_stage_progress(state, "missing", "investigate", "查看正文")
    bad_type = _append_stage_progress(state, stage_id, "read", "查看正文")
    bad_refocus = _append_stage_progress(state, stage_id, "refocus", "方向变化写进后续 summary")
    bad_issue = _append_stage_progress(state, stage_id, "issue", "工具错误保留在 actions")

    assert bad_stage["ok"] is False
    assert bad_stage["errors"][0]["message"] == "unknown stage_id"
    assert bad_type["ok"] is False
    assert bad_type["errors"][0]["message"] == "invalid progress type"
    assert bad_type["errors"][0]["allowed"] == [
        "compare",
        "investigate",
        "verify_absence",
    ]
    assert bad_refocus["ok"] is False
    assert bad_refocus["errors"][0]["message"] == "invalid progress type"
    assert bad_issue["ok"] is False
    assert bad_issue["errors"][0]["message"] == "invalid progress type"
    assert state.reading_stages[0]["progress"] == []


def test_record_stage_evidence_and_review_returns_notes_in_record_order():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]

    first = _record_stage_evidence(
        state,
        stage_id,
        "contact_phone",
        [inline_id],
        "联系人段落同时给出联系人和电话。",
        supports="可支持联系方式相关判断。",
        limits="不能证明名单字段。",
    )
    second = _record_stage_evidence(
        state,
        stage_id,
        "contact_phone",
        [inline_id],
        "同一证据可复用到电话字段。",
        supports="可支持电话字段。",
        limits="仍需保留精确 inline id。",
    )
    review = _review_stage_evidence(state, stage_id)

    assert first["ok"] is True
    assert first["evidence_note"]["note_id"] == "stage-1-evidence-1"
    assert first["evidence_note"]["field_name"] == "contact_phone"
    assert second["evidence_note"]["note_id"] == "stage-1-evidence-2"
    assert [note["note_id"] for note in review["evidence_notes"]] == [
        "stage-1-evidence-1",
        "stage-1-evidence-2",
    ]
    assert review["evidence_notes"][0]["observation"] == "联系人段落同时给出联系人和电话。"


def test_review_stage_evidence_requires_active_stage():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    allowed = _review_stage_evidence(state, stage_id)
    _append_stage_progress(state, stage_id, "investigate", "测试关闭 stage 前已有阅读进展。")
    _complete_stage(
        state,
        stage_id,
        "完成当前阶段。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [],
                "status": "failed",
                "failure_reason": "测试关闭 stage。",
                "rationale": "测试关闭 stage 后不能再复看。",
            }
        ],
    )
    after_complete = _review_stage_evidence(state, stage_id)

    assert allowed["ok"] is True
    assert after_complete["ok"] is False
    assert after_complete["errors"][0]["message"] == "review_stage_evidence requires current active stage"


def test_reading_tools_require_reading_progress_after_start_stage():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]

    blocked = _read_blocks(state, "dp-p-1", indexes=[0], reason="还没声明阅读进展就读取")
    progress = _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    allowed = _read_blocks(state, "dp-p-1", indexes=[0], reason="进入阅读期后读取联系人段落")

    assert blocked["ok"] is False
    assert blocked["errors"][0]["message"] == "reading tools require current stage reading progress"
    assert blocked["errors"][0]["stage_id"] == stage_id
    assert progress["ok"] is True
    assert allowed["section_id"] == "dp-p-1"


def test_complete_stage_requires_reading_progress_and_non_empty_fields():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]

    old_conclude = _append_stage_progress(state, stage_id, "conclude", "旧入口不能进入 conclude。")
    premature = _complete_stage(
        state,
        stage_id,
        "不能在没有阅读进展时完成。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [],
                "status": "failed",
                "failure_reason": "测试字段。",
                "rationale": "测试字段。",
            }
        ],
    )
    investigate = _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    empty_fields = _complete_stage(state, stage_id, "不能空完成。", [])

    assert old_conclude["ok"] is False
    assert old_conclude["errors"][0]["message"] == "invalid progress type"
    assert premature["ok"] is False
    assert premature["errors"][0]["message"] == "complete_stage requires prior reading progress"
    assert empty_fields["ok"] is False
    assert empty_fields["errors"][0]["message"] == "fields must be a non-empty list"
    assert state.reading_stages[0]["progress"] == [investigate["progress"]]
    assert state.reading_stages[0]["status"] == "in_progress"


def test_complete_stage_rejects_missing_field_without_mutation():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "联系人段落给出电话。")

    missing = _complete_stage(
        state,
        stage_id,
        "证据还不完整，不能完成阶段。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "联系人段落给出了部分信息。",
                "missing": "还没有确认是否有后续段落覆盖更新电话。",
            }
        ],
    )
    assert missing["ok"] is False
    assert missing["errors"][0]["message"] == "field has missing evidence"
    assert [event["type"] for event in state.reading_stages[0]["progress"]] == ["investigate"]
    assert state.reading_stages[0]["status"] == "in_progress"
    assert state.field_states == {}

    allowed = _complete_stage(
        state,
        stage_id,
        "证据已经完整，可以写电话字段。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "inline 证据直接给出电话。",
            }
        ],
    )

    assert allowed["ok"] is True
    assert state.reading_stages[0]["status"] == "completed"
    assert state.field_states["contact_phone"]["evidence_ids"] == [inline_id]


def test_record_stage_evidence_requires_observed_precise_evidence():
    state = _state()
    stage_id = _start_stage(state, "理解名单来源", "看名单附近内容", "名单可能给出字段证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")

    coarse_text = _record_stage_evidence(state, stage_id, "contact_phone", ["dp-p-1"], "整段文字还不够精确。")
    unknown = _record_stage_evidence(state, stage_id, "contact_phone", ["missing"], "不存在的证据。")
    unknown_field = _record_stage_evidence(state, stage_id, "missing_field", ["dp-p-1"], "字段不存在。")

    assert coarse_text["ok"] is False
    assert coarse_text["errors"][0]["message"] == "text evidence must use inline evidence ids from preview_inline_evidence"
    assert unknown["ok"] is False
    assert unknown["errors"][0]["message"] == "unknown evidence ids"
    assert unknown_field["ok"] is False
    assert unknown_field["errors"][0]["message"] == "unknown field"
    assert state.reading_stages[0]["evidence_notes"] == []


def test_complete_stage_records_field_rationale_without_separate_evidence_note_ids():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "联系人段落给出电话。")

    result = _complete_stage(
        state,
        stage_id,
        "联系人证据已经读完，可以写电话字段。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "inline 证据直接给出电话 12345。",
            }
        ],
    )

    assert result["ok"] is True
    field = state.field_states["contact_phone"]
    assert field["stage_id"] == stage_id
    assert field["rationale"] == "inline 证据直接给出电话 12345。"
    assert "evidence_note_ids" not in field
    assert state.actions[-1]["tool_name"] == "complete_stage"
    assert state.actions[-1]["args"]["fields"][0]["rationale"] == "inline 证据直接给出电话 12345。"
    assert "evidence_note_ids" not in state.actions[-1]["args"]["fields"][0]


def test_complete_stage_requires_evidence_recorded_for_same_field():
    state = _state()
    state.task_spec.fields.append(SimpleNamespace(name="other_phone", type="string", required=False))
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    _record_stage_evidence(state, stage_id, "other_phone", [inline_id], "这条证据只先挂到 other_phone。")

    wrong_field = _complete_stage(
        state,
        stage_id,
        "尝试用挂到 other_phone 的证据写 contact_phone。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "证据没有先挂到 contact_phone。",
            }
        ],
    )

    assert wrong_field["ok"] is False
    assert wrong_field["errors"][0]["message"] == "evidence ids must be recorded for this field before complete_stage"
    assert wrong_field["errors"][0]["ids"] == [inline_id]
    assert state.field_states == {}

    _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "同一证据现在挂到 contact_phone。")
    allowed = _complete_stage(
        state,
        stage_id,
        "联系人证据已经逐字段挂账。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "证据已经挂到 contact_phone。",
            }
        ],
    )

    assert allowed["ok"] is True
    assert state.field_states["contact_phone"]["evidence_ids"] == [inline_id]


def test_complete_stage_allows_null_value_without_evidence_but_checks_recorded_evidence_if_present():
    state = _state()
    state.task_spec.fields = [SimpleNamespace(name="contact_phone", type="null", required=False)]
    stage_id = _start_stage(state, "确认联系人缺失", "看联系人段落", "联系人字段可能为空。")["stage"]["stage_id"]
    _append_stage_progress(state, stage_id, "verify_absence", "联系人字段可以为空。")

    no_evidence = _complete_stage(
        state,
        stage_id,
        "字段为空且不需要证据。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [],
                "status": "resolved",
                "rationale": "该字段按类型可为空。",
            }
        ],
    )

    assert no_evidence["ok"] is True

    state = _state()
    state.task_spec.fields = [SimpleNamespace(name="contact_phone", type="null", required=False)]
    stage_id = _start_stage(state, "确认联系人缺失", "看联系人段落", "联系人字段可能为空。")["stage"]["stage_id"]
    _append_stage_progress(state, stage_id, "verify_absence", "联系人字段可以为空。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    with_unrecorded_evidence = _complete_stage(
        state,
        stage_id,
        "字段为空但引用了证据。",
        [
            {
                "name": "contact_phone",
                "value": None,
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "空值字段如果引用证据，也要先逐字段挂账。",
            }
        ],
    )

    assert with_unrecorded_evidence["ok"] is False
    assert with_unrecorded_evidence["errors"][0]["message"] == "evidence ids must be recorded for this field before complete_stage"


def test_complete_stage_is_atomic_when_any_field_is_invalid():
    state = _state()
    state.task_spec.fields.append(SimpleNamespace(name="other_phone", type="string", required=False))
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "联系人段落给出电话。")

    result = _complete_stage(
        state,
        stage_id,
        "尝试一次写两个字段。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "inline 证据直接给出电话。",
            },
            {
                "name": "other_phone",
                "value": "67890",
                "evidence_ids": ["missing"],
                "status": "resolved",
                "rationale": "这个字段引用了不存在的证据。",
            },
        ],
    )

    assert result["ok"] is False
    assert result["errors"][0]["message"] == "unknown evidence ids"
    assert state.field_states == {}
    assert state.reading_stages[0]["status"] == "in_progress"


def test_set_field_rejects_unknown_stage_id():
    state = _state()
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]

    bad_stage = _set_field(
        state,
        "contact_phone",
        "12345",
        [inline_id],
        "resolved",
        None,
        stage_id="missing",
        rationale="尝试引用不存在的阶段。",
    )

    assert bad_stage["ok"] is False
    assert bad_stage["errors"][0]["message"] == "unknown stage_id"


def test_complete_stage_failure_keeps_stage_readable():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    failed = _complete_stage(
        state,
        stage_id,
        "证据还不够，不能完成。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": ["missing"],
                "status": "resolved",
                "rationale": "引用了不存在的证据。",
            }
        ],
    )

    read_more = _read_blocks(state, "dp-p-long", indexes=[0], reason="complete_stage 失败后继续读")
    progress = _append_stage_progress(state, stage_id, "investigate", "失败后继续细化同一阶段。")

    assert failed["ok"] is False
    assert failed["errors"][0]["message"] == "unknown evidence ids"
    assert read_more["section_id"] == "dp-p-long"
    assert progress["ok"] is True
    assert state.reading_stages[0]["status"] == "in_progress"
    assert state.field_states == {}
    assert state.observed_evidence_ids == {"dp-p-1", "dp-p-long"}


def test_complete_stage_success_blocks_new_notes_because_stage_is_completed():
    state = _state()
    stage_id = _start_stage(state, "理解联系人来源", "看联系人段落", "联系人字段需要正文证据。")["stage"][
        "stage_id"
    ]
    _append_stage_progress(state, stage_id, "investigate", "准备读取联系人段落。")
    _read_blocks(state, "dp-p-1", indexes=[0], reason="读取联系人段落")
    inline = _preview_inline_evidence(state, "dp-p-1", start_index=0, count=1, reason="细化联系人证据")
    inline_id = inline["inline_evidence"][0]["inline_id"]
    _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "联系人段落给出电话。")
    completed = _complete_stage(
        state,
        stage_id,
        "联系人证据已经读完。",
        [
            {
                "name": "contact_phone",
                "value": "12345",
                "evidence_ids": [inline_id],
                "status": "resolved",
                "rationale": "inline 证据直接给出电话。",
            }
        ],
    )
    blocked_stage = _start_stage(state, "下一阶段", "继续读取", "上一阶段已经完成，可以开新阶段。")
    blocked_note = _record_stage_evidence(state, stage_id, "contact_phone", [inline_id], "完成后不能再记 note。")

    assert completed["ok"] is True
    assert blocked_stage["ok"] is True
    assert blocked_note["ok"] is False
    assert blocked_note["errors"][0]["message"] == "record_stage_evidence requires current active stage"
    assert blocked_note["errors"][0]["stage_id"] == stage_id
    assert state.reading_stages[0]["stage_id"] == stage_id
    assert state.reading_stages[0]["status"] == "completed"
    assert [event["type"] for event in state.reading_stages[0]["progress"]] == ["investigate"]
    assert state.reading_stages[0]["evidence_notes"][0]["field_name"] == "contact_phone"


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
        "start_stage",
        "append_stage_progress",
        "record_stage_evidence",
        "review_stage_evidence",
        "complete_stage",
        "overview",
        "read_section",
        "read_blocks",
        "read_block_range",
        "read_list",
        "query_table",
        "preview_inline_evidence",
        "finish",
    ]
    start_stage = tools[names.index("start_stage")]
    start_schema = getattr(start_stage, "args_schema", None)
    start_fields = getattr(start_schema, "model_fields", None) or getattr(start_schema, "__fields__", {})
    assert {"title", "focus", "basis"} <= set(start_fields)
    assert "state" not in start_fields
    assert "reason" not in start_fields
    start_description = _tool_description(start_stage)
    assert "Start a new stage" in start_description
    assert "not a field checklist" in start_description
    assert "related evidence-to-field writing unit" in start_description
    assert "Put related fields in the same stage" in start_description
    assert "Do not put unrelated fields in the same stage" in start_description
    assert "hypoth" not in start_description.lower()
    progress = tools[names.index("append_stage_progress")]
    progress_schema = getattr(progress, "args_schema", None)
    progress_fields = getattr(progress_schema, "model_fields", None) or getattr(progress_schema, "__fields__", {})
    assert {"stage_id", "type", "summary"} <= set(progress_fields)
    assert "reason" not in progress_fields
    progress_description = _tool_description(progress)
    assert "investigate, compare, or verify_absence" in progress_description
    assert "complete_stage" in progress_description
    assert "refocus" not in progress_description
    assert "issue" not in progress_description
    assert "Do not append progress just for display" in progress_description
    record = tools[names.index("record_stage_evidence")]
    record_schema = getattr(record, "args_schema", None)
    record_fields = getattr(record_schema, "model_fields", None) or getattr(record_schema, "__fields__", {})
    assert {"stage_id", "field_name", "evidence_ids", "observation", "supports", "limits"} <= set(record_fields)
    assert "reason" not in record_fields
    record_description = _tool_description(record)
    assert "field-scoped candidate evidence note" in record_description
    assert "one field" in record_description
    review = tools[names.index("review_stage_evidence")]
    review_schema = getattr(review, "args_schema", None)
    review_fields = getattr(review_schema, "model_fields", None) or getattr(review_schema, "__fields__", {})
    assert {"stage_id"} <= set(review_fields)
    assert "recorded order" in _tool_description(review)
    complete = tools[names.index("complete_stage")]
    complete_schema = getattr(complete, "args_schema", None)
    complete_fields = getattr(complete_schema, "model_fields", None) or getattr(complete_schema, "__fields__", {})
    assert {"stage_id", "finding", "fields"} <= set(complete_fields)
    assert "reason" not in complete_fields
    complete_description = _tool_description(complete)
    assert "non-empty" in complete_description
    assert "missing" in complete_description
    assert "record_stage_evidence with the same field name" in complete_description
    assert "whole call fails" in complete_description
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
    assert "why you are reading" in _tool_description(read_section)
    assert "actual DOM descendants" in _tool_description(read_section)
    read_blocks = tools[names.index("read_blocks")]
    blocks_schema = getattr(read_blocks, "args_schema", None)
    blocks_fields = getattr(blocks_schema, "model_fields", None) or getattr(blocks_schema, "__fields__", {})
    assert "indexes" in blocks_fields
    assert "reason" in blocks_fields
    assert "offset" not in blocks_fields
    assert "number" not in blocks_fields
    blocks_description = _tool_description(read_blocks)
    assert "why you are reading" in blocks_description
    assert "section container, heading, or leaf block id" in blocks_description
    assert "selected block indexes" in blocks_description
    assert "not following siblings" in blocks_description
    assert "leaf block id" in blocks_description
    read_block_range = tools[names.index("read_block_range")]
    range_schema = getattr(read_block_range, "args_schema", None)
    range_fields = getattr(range_schema, "model_fields", None) or getattr(range_schema, "__fields__", {})
    assert "start_index" in range_fields
    assert "count" in range_fields
    assert "reason" in range_fields
    assert "indexes" not in range_fields
    range_description = _tool_description(read_block_range)
    assert "why you are reading" in range_description
    assert "contiguous range" in range_description
    assert "Use read_blocks" in range_description
    read_list = tools[names.index("read_list")]
    list_schema = getattr(read_list, "args_schema", None)
    list_fields = getattr(list_schema, "model_fields", None) or getattr(list_schema, "__fields__", {})
    assert "item_offset" in list_fields
    assert "reason" in list_fields
    list_description = _tool_description(read_list)
    assert "why you are reading" in list_description
    assert "Read list items" in list_description
    assert "top-level list id" in list_description
    assert "block_offset=0" in list_description
    query_table = tools[names.index("query_table")]
    table_schema = getattr(query_table, "args_schema", None)
    table_fields = getattr(table_schema, "model_fields", None) or getattr(table_schema, "__fields__", {})
    assert "block_offset" in table_fields
    assert "sql" in table_fields
    assert "reason" in table_fields
    query_table_description = _tool_description(query_table)
    assert "why you are querying" in query_table_description
    assert "top-level table id" in query_table_description
    assert "block_offset=0" in query_table_description
    assert "double quotes" in query_table_description
    preview_inline = tools[names.index("preview_inline_evidence")]
    preview_schema = getattr(preview_inline, "args_schema", None)
    preview_fields = getattr(preview_schema, "model_fields", None) or getattr(preview_schema, "__fields__", {})
    assert "source_id" in preview_fields
    assert "start_index" in preview_fields
    assert "count" in preview_fields
    assert "reason" in preview_fields
    preview_description = _tool_description(preview_inline)
    assert "why you are previewing" in preview_description
    assert "Only use this after reading a text block" in preview_description
    assert "inline_id" in preview_description
    assert "complete_stage" in preview_description
    start_stage_description = " ".join(_tool_description(tools[names.index("start_stage")]).split())
    assert "Start a new stage" in start_stage_description
    assert "After start_stage" in start_stage_description
    progress_description = " ".join(_tool_description(tools[names.index("append_stage_progress")]).split())
    assert "type controls what changed and what tools are allowed next" in progress_description
    assert "Put related fields in the same stage when they are being resolved from the same part of the document or the same comparison" in progress_description
    assert "Do not put unrelated fields in the same stage" in progress_description
    assert "If the next field is not related to the current stage's evidence or comparison, complete the current stage before starting a new stage" in progress_description
    assert "Only keep multiple fields in one stage when they share the same clause, evidence path, table, list, or comparison chain" not in progress_description
    assert "Only write multiple fields in one stage when they share the same section, table, list, or comparison chain" not in progress_description
    assert "Same section alone is not enough" not in progress_description
    assert "remaining fields, remaining obligations, or remaining provisions" not in progress_description
    assert "hypoth" not in progress_description.lower()
    assert "polarity" not in progress_description.lower()
    assert "decision direction" not in progress_description.lower()
    assert "investigate:" in progress_description
    assert "compare:" in progress_description
    assert "verify_absence:" in progress_description
    assert "Forbidden after investigate: finish" in progress_description
    assert "Forbidden after compare: finish" in progress_description
    assert "Forbidden after verify_absence: finish" in progress_description
    assert "Do not append progress just for display" in progress_description
    complete_description = " ".join(_tool_description(complete).split())
    assert "read_blocks" in complete_description
    assert "read_block_range" in complete_description
    assert "preview_inline_evidence" in complete_description
    assert "inline ids" in complete_description
    assert "row ids" in complete_description
    assert "item ids" in complete_description
    assert "query_table" in complete_description
    read_tools_with_reason = {
        "overview",
        "read_section",
        "read_blocks",
        "read_block_range",
        "read_list",
        "query_table",
        "preview_inline_evidence",
    }
    for tool in tools:
        name = _tool_name(tool)
        schema = getattr(tool, "args_schema", None)
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
        if name in read_tools_with_reason:
            assert "reason" in fields, name
            assert _field_is_required(fields["reason"]), name
        else:
            assert "reason" not in fields, name
    assert "enum fields" in complete_description
    assert '{"variant": "name", "value": ...}' in complete_description
    assert "null variant" in complete_description
    assert "field-level rationale" in complete_description


def test_finish_exposes_required_confirmation_argument_for_openai_schema():
    tools = build_tools(_state())
    finish = tools[[_tool_name(tool) for tool in tools].index("finish")]
    schema = getattr(finish, "args_schema", None)
    fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})

    assert {"confirm"} <= set(fields)
    assert _field_is_required(fields["confirm"])

    openai_schema = convert_to_openai_tool(finish)
    parameters = openai_schema["function"]["parameters"]
    assert parameters["required"] == ["confirm"]
    assert parameters["properties"]["confirm"] == {"const": "finish", "type": "string"}


def _tool_name(tool):
    return getattr(tool, "name", getattr(tool, "__name__", ""))


def _tool_description(tool):
    return getattr(tool, "description", getattr(tool, "__doc__", "") or "")


def _field_is_required(field) -> bool:
    is_required = getattr(field, "is_required", None)
    if callable(is_required):
        return bool(is_required())
    return bool(getattr(field, "required", False))


def _find_tree_node(nodes, node_id):
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = _find_tree_node(node.get("children", []), node_id)
        if found is not None:
            return found
    return None
