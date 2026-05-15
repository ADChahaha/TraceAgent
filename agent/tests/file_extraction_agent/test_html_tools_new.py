from __future__ import annotations

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    __all__ as html_tools_all,
    _bind_evidence,
    _read,
    _review_evidences,
    _skip_read,
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


def _large_collection_state():
    list_items = "\n".join(f"<li>服务项目 {index}</li>" for index in range(1, 36))
    table_rows = "\n".join(f"<tr><td>费用 {index}</td><td>{index}</td></tr>" for index in range(1, 36))
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "large.html",
                "html": f"""
                <h1>大列表</h1>
                <h2>明细</h2>
                <ul>{list_items}</ul>
                <table>
                  <tr><th>项目</th><th>金额</th></tr>
                  {table_rows}
                </table>
                """,
            }
        ],
        task_spec={
            "fields": [
                {"name": "items", "type": "list[string]", "required": False},
                {"name": "fees", "type": "list[number]", "required": False},
            ]
        },
    )
    return build_graph_state(extraction_input)


def _enum_state():
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "contract.html",
                "html": """
                <h1>合同</h1>
                <h2>保密条款</h2>
                <p>接收方只能为项目目的使用保密信息。协议未提及反向工程。</p>
                """,
            }
        ],
        task_spec={
            "fields": [
                {
                    "name": "limited_use_decision",
                    "type": "enum",
                    "required": True,
                    "variants": [
                        {"name": "Entailment", "type": "list[string]"},
                        {"name": "NotMentioned", "type": "null"},
                    ],
                }
            ]
        },
    )
    return build_graph_state(extraction_input)


def _paths():
    return {
        "paragraph": "/001-company-公司资料/001-概况/001-公司成立于2020年。总部位于上海.md",
        "list": "/001-company-公司资料/001-概况/002-提供系统维护.list",
        "table": "/001-company-公司资料/001-概况/003-费用明细.table",
    }


def _path_ids(state, paths):
    return {name: state.document.path_id(path) for name, path in paths.items()}


def _large_paths():
    return {
        "list": "/001-large-大列表/001-明细/001-服务项目 1.list",
        "table": "/001-large-大列表/001-明细/002-项目 金额.table",
    }


def _first_path_by_kind(state, kind: str):
    for path, node in state.document.nodes_by_path.items():
        if node.kind == kind:
            return state.document.path_id(path)
    raise AssertionError(f"missing {kind} path")


def test_build_tools_exposes_read_judgement_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "tree",
        "read",
        "bind_evidence",
        "skip_read",
        "review_evidences",
        "write_field",
        "submit_result",
    ]


def test_module_exports_current_review_helper():
    assert "_review_evidences" in html_tools_all
    assert "_anchors" not in html_tools_all
    assert "_query_table" not in html_tools_all
    assert "_review_field" not in html_tools_all


def test_read_requires_bind_or_skip_before_other_tools():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    read_result = _read(state, path_ids["paragraph"], reason="读取成立年份段落。")
    blocked_tree = _tree(state, "[0000]", depth=1, reason="还没判断上次 read，不能继续展开 tree。")
    blocked_read = _read(state, path_ids["list"], reason="还没判断上次 read，不能继续 read。")
    skipped = _skip_read(state, reason="刚读段落不作为当前字段证据，关闭 read 判断。")
    next_read = _read(state, path_ids["list"], reason="上次 read 已判断完，继续读取列表。")

    assert read_result["ok"] is True
    assert blocked_tree["ok"] is False
    assert blocked_tree["errors"][0]["code"] == "READ_JUDGEMENT_REQUIRED"
    assert blocked_read["ok"] is False
    assert blocked_read["errors"][0]["code"] == "READ_JUDGEMENT_REQUIRED"
    assert skipped["ok"] is True
    assert skipped["skipped"]["path_id"] == path_ids["paragraph"]
    assert next_read["ok"] is True


def test_bind_evidence_uses_current_read_block_and_review_expands_inline():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    missing_read = _bind_evidence(state, "founded_year", reason="没有 read，不能绑定。")
    _read(state, path_ids["paragraph"], reason="读取成立年份段落。")
    bound = _bind_evidence(
        state,
        bindings=[{"field_id": "founded_year"}, {"field_id": "missing_required"}],
        reason="当前段落可能支持两个字段，一次绑定到两个候选池。",
    )
    review = _review_evidences(state, "founded_year", reason="展开 founded_year 候选 block 为 inline。")

    assert missing_read["ok"] is False
    assert missing_read["errors"][0]["code"] == "READ_REQUIRED"
    assert bound["ok"] is True
    assert bound["bindings"][0]["candidate_evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert state.evidence_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert state.evidence_states["missing_required"]["evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert review["candidate_evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert review["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001", "S002"]}]
    assert review["evidence_texts"] == [
        {"path_id": path_ids["paragraph"], "selector": "S001", "text": "公司成立于2020年。"},
        {"path_id": path_ids["paragraph"], "selector": "S002", "text": "总部位于上海。"},
    ]


def test_bind_evidence_cannot_reuse_read_after_other_tool():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    _read(state, path_ids["paragraph"], reason="读取成立年份段落。")
    _bind_evidence(state, "founded_year", reason="绑定当前 read block，pending read 关闭。")
    stale = _bind_evidence(state, "deposit", reason="不能回头绑定已经关闭的旧 read block。")

    assert stale["ok"] is False
    assert stale["errors"][0]["code"] == "READ_REQUIRED"
    assert "deposit" not in state.evidence_states


def test_list_and_table_read_return_all_rows_and_review_expands_all_inline():
    state = _large_collection_state()
    paths = _large_paths()
    path_ids = _path_ids(state, paths)

    list_result = _read(state, path_ids["list"], reason="读取完整列表。")
    _bind_evidence(state, "items", reason="完整列表可能支持 items，绑定 list block。")
    list_review = _review_evidences(state, "items", reason="展开 list block。")
    _read(state, path_ids["table"], reason="读取完整表格。")
    _bind_evidence(state, "fees", reason="完整表格可能支持 fees，绑定 table block。")
    table_review = _review_evidences(state, "fees", reason="展开 table block。")

    assert list_result["has_more"] is False
    assert "[I035] 服务项目 35" in list_result["text"]
    assert list_review["evidence"] == [{"path_id": path_ids["list"], "items": [f"I{index:03d}" for index in range(1, 36)]}]
    assert "| R035 | 费用 35 | 35 |" in state.document.read_markdown(paths["table"], limit=0)["text"]
    assert table_review["evidence"] == [{"path_id": path_ids["table"], "rows": [f"R{index:03d}" for index in range(1, 36)]}]


def test_write_field_requires_reviewed_inline_evidence_not_block_evidence():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    _read(state, path_ids["paragraph"], reason="读取成立年份段落。")
    _bind_evidence(state, "founded_year", reason="当前段落支持 founded_year，绑定 block。")
    blocked_before_review = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="还没 review_evidences，不能写 resolved 非 null 字段。",
    )
    _review_evidences(state, "founded_year", reason="展开候选 block。")
    blocked_block_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"]}],
        status="resolved",
        reason="final_evidence 不能使用 block selector。",
    )

    assert blocked_before_review["ok"] is False
    assert blocked_before_review["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"
    assert blocked_block_evidence["ok"] is False
    assert blocked_block_evidence["errors"][0]["code"] == "INLINE_FINAL_EVIDENCE_REQUIRED"
    _review_evidences(state, "founded_year", reason="失败写入后重新 review，确保 write 前紧邻 review。")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="使用刚刚 review_evidences 返回的 S001 写入字段。",
    )
    assert written["ok"] is True
    assert written["field"]["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001"]}]
    assert written["field"]["evidence_texts"] == [
        {"path_id": path_ids["paragraph"], "selector": "S001", "text": "公司成立于2020年。"}
    ]
    _review_evidences(state, "founded_year", reason="检查未 review 编号前重新 review。")
    blocked_unreviewed_inline = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"], "sentences": ["S999"]}],
        status="resolved",
        reason="S999 没有出现在刚刚的 review_evidences 返回值中。",
    )
    assert blocked_unreviewed_inline["ok"] is False
    assert blocked_unreviewed_inline["errors"][0]["code"] == "UNREVIEWED_FINAL_EVIDENCE"


def test_write_field_requires_immediately_preceding_same_field_review():
    stale_state = _state()
    paths = _paths()
    path_ids = _path_ids(stale_state, paths)

    _read(stale_state, path_ids["paragraph"], reason="读取成立年份段落。")
    _bind_evidence(stale_state, "founded_year", reason="绑定 founded_year 候选 block。")
    _review_evidences(stale_state, "founded_year", reason="先 review founded_year。")
    _read(stale_state, path_ids["list"], reason="插入一次其它 read，让 review 不再紧邻 write。")
    _skip_read(stale_state, reason="列表和 founded_year 无关。")
    stale_write = _write_field(
        stale_state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="不能用已经被其它工具隔开的 review 写字段。",
    )

    wrong_field_state = _state()
    wrong_paths = _path_ids(wrong_field_state, _paths())
    _read(wrong_field_state, wrong_paths["paragraph"], reason="读取成立年份段落。")
    _bind_evidence(wrong_field_state, "founded_year", reason="绑定 founded_year 候选 block。")
    _review_evidences(wrong_field_state, "founded_year", reason="只 review founded_year。")
    wrong_field_write = _write_field(
        wrong_field_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
        reason="review 了 founded_year，不能紧跟写 missing_required。",
    )

    assert stale_write["ok"] is False
    assert stale_write["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"
    assert wrong_field_write["ok"] is False
    assert wrong_field_write["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"

    failed_review_state = _state()
    failed_paths = _path_ids(failed_review_state, _paths())
    _read(failed_review_state, failed_paths["paragraph"], reason="读取成立年份段落。")
    _bind_evidence(failed_review_state, "founded_year", reason="绑定 founded_year 候选 block。")
    _review_evidences(failed_review_state, "founded_year", reason="先成功 review founded_year。")
    failed_review = _review_evidences(failed_review_state, "unknown", reason="随后一次失败 review 不能满足 write 前 review。")
    blocked_after_failed_review = _write_field(
        failed_review_state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": failed_paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="最后一个 review 已失败，不能用更早的 review 写字段。",
    )

    assert failed_review["ok"] is False
    assert blocked_after_failed_review["ok"] is False
    assert blocked_after_failed_review["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"


def test_missing_and_null_enum_values_can_use_empty_evidence_after_review():
    missing_state = _state()
    enum_state = _enum_state()

    blocked_missing = _write_field(
        missing_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
        reason="没有紧跟 review，不能写 missing。",
    )
    _review_evidences(missing_state, "missing_required", reason="写 missing 前先 review 空候选。")
    missing = _write_field(
        missing_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
        reason="文档未提及该字段，写 missing。",
    )
    blocked_null_enum = _write_field(
        enum_state,
        "limited_use_decision",
        {"variant": "NotMentioned", "value": None},
        final_evidence=[],
        status="resolved",
        reason="没有紧跟 review，不能写 null enum。",
    )
    _review_evidences(enum_state, "limited_use_decision", reason="写 null enum 前先 review 空候选。")
    null_enum = _write_field(
        enum_state,
        "limited_use_decision",
        {"variant": "NotMentioned", "value": None},
        final_evidence=[],
        status="resolved",
        reason="null enum variant 表示未提及，可以空证据。",
    )

    assert blocked_missing["ok"] is False
    assert blocked_missing["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"
    assert missing["ok"] is True
    assert blocked_null_enum["ok"] is False
    assert blocked_null_enum["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"
    assert null_enum["ok"] is True


def test_submit_result_requires_final_evidence_for_resolved_non_null_values():
    state = _enum_state()

    blocked_before_review = _write_field(
        state,
        "limited_use_decision",
        {"variant": "Entailment", "value": ["接收方只能为项目目的使用保密信息。"]},
        final_evidence=[],
        status="resolved",
        reason="非 null enum 没有 review，不能直接写入。",
    )
    _read(state, _first_path_by_kind(state, "paragraph"), reason="读取可能支持 enum 的段落。")
    _bind_evidence(state, "limited_use_decision", reason="当前段落可能支持 enum 字段，绑定 block。")
    _review_evidences(state, "limited_use_decision", reason="写字段前先 review 候选证据。")
    written = _write_field(
        state,
        "limited_use_decision",
        {"variant": "Entailment", "value": ["接收方只能为项目目的使用保密信息。"]},
        final_evidence=[],
        status="resolved",
        reason="先写入非 null enum 草稿。",
    )
    blocked = _submit_result(state, reason="提交时拒绝非 null enum 空证据。")

    assert blocked_before_review["ok"] is False
    assert blocked_before_review["errors"][0]["code"] == "IMMEDIATE_REVIEW_REQUIRED"
    assert written["ok"] is True
    assert blocked["ok"] is False
    assert blocked["errors"][0]["code"] == "MISSING_FINAL_EVIDENCE"


def test_read_write_reject_raw_paths_and_use_path_id_through_review():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    raw_path_result = _read(state, paths["paragraph"], reason="raw path 不再是模型可见 locator。")
    read_result = _read(state, path_ids["paragraph"], reason="读取 path_id 指向的段落。")
    _bind_evidence(state, "founded_year", reason="绑定 canonicalized paragraph block。")
    review = _review_evidences(state, "founded_year", reason="展开 canonicalized paragraph block。")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": path_ids["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="write_field 使用 path_id selector。",
    )
    raw_path_final_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="raw path 不能伪装成 path_id selector。",
    )

    assert raw_path_result["ok"] is False
    assert read_result["path_id"] == path_ids["paragraph"]
    assert review["candidate_evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert written["ok"] is True
    assert written["field"]["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001"]}]
    _review_evidences(state, "founded_year", reason="raw path 校验前重新 review，确保错误来自 selector 本身。")
    raw_path_final_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[{"path_id": paths["paragraph"], "sentences": ["S001"]}],
        status="resolved",
        reason="raw path 不能伪装成 path_id selector。",
    )
    assert raw_path_final_evidence["ok"] is False
    assert raw_path_final_evidence["errors"][0]["code"] == "UNREVIEWED_FINAL_EVIDENCE"
