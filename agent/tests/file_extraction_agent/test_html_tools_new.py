from __future__ import annotations

import inspect

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    __all__ as html_tools_all,
    _add_candidate_evidence,
    _read,
    _review_evidences,
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


def _multi_section_state():
    extraction_input = build_graph_input(
        documents=[
            {
                "filename": "sections.html",
                "html": """
                <h1>连续阅读</h1>
                <h2>第一节</h2>
                <p>第一节第一段。</p>
                <p>第一节第二段。</p>
                <p>第一节第三段。</p>
                <p>第一节第四段。</p>
                <h2>第二节</h2>
                <p>第二节第一段。</p>
                <p>第二节第二段。</p>
                """,
            }
        ],
        task_spec={"fields": [{"name": "summary", "type": "string", "required": False}]},
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


def _locators(state, paths):
    return {name: f"evidence://{path_id}" for name, path_id in _path_ids(state, paths).items()}


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


def _paragraph_path_id_containing(state, text: str) -> str:
    for path, node in state.document.nodes_by_path.items():
        if node.kind == "paragraph" and text in node.text:
            return state.document.path_id(path)
    raise AssertionError(f"missing paragraph containing {text}")


def test_build_tools_exposes_candidate_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == [
        "tree",
        "read",
        "add_candidate_evidence",
        "review_evidences",
        "write_field",
        "submit_result",
    ]


def test_module_exports_current_review_helper():
    assert "_review_evidences" in html_tools_all
    assert "_anchors" not in html_tools_all
    assert "_query_table" not in html_tools_all
    assert "_review_field" not in html_tools_all


def test_internal_tool_helpers_do_not_accept_reason_parameter():
    helpers = [_tree, _read, _add_candidate_evidence, _review_evidences, _write_field, _submit_result]

    for helper in helpers:
        assert "reason" not in inspect.signature(helper).parameters


def test_read_allows_free_navigation_after_successful_read():
    state = _state()
    paths = _paths()
    locators = _locators(state, paths)

    read_result = _read(state, locators["paragraph"])
    next_tree = _tree(state, "", depth=1)
    next_read = _read(state, locators["list"])

    assert read_result["ok"] is True
    assert next_tree["ok"] is True
    assert next_read["ok"] is True


def test_tool_path_arguments_use_evidence_links_and_write_final_evidence_copies_review_links():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    tree = _tree(state, "", depth=2)
    read = _read(state, locators["paragraph"])
    bound = _add_candidate_evidence(state, "founded_year", path_id=locators["paragraph"])
    review = _review_evidences(state, "founded_year")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )

    assert tree["ok"] is True
    assert "evidence://0001" in tree["text"]
    assert read["ok"] is True
    assert read["locator"] == locators["paragraph"]
    assert bound["ok"] is True
    assert "bindings" not in bound
    assert bound["field_id"] == "founded_year"
    assert bound["candidate_evidence"] == [locators["paragraph"]]
    assert state.evidence_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert review["candidate_evidence"] == [locators["paragraph"]]
    assert review["evidence"] == [f"{locators['paragraph']}/S001", f"{locators['paragraph']}/S002"]
    assert written["ok"] is True
    assert written["field"]["evidence"] == [f"{locators['paragraph']}/S001"]
    assert state.field_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001"]}]


def test_bare_path_ids_are_rejected_for_model_facing_path_arguments():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)

    read = _read(state, path_ids["paragraph"])
    bind = _add_candidate_evidence(state, "founded_year", path_id=path_ids["paragraph"])

    assert read["ok"] is False
    assert read["errors"][0]["code"] == "BAD_LOCATOR"
    assert bind["ok"] is False
    assert bind["errors"][0]["code"] == "BAD_LOCATOR"


def test_read_reads_one_block_and_exposes_only_path_id_argument():
    state = _multi_section_state()
    first = _paragraph_path_id_containing(state, "第一节第一段")
    tools = {getattr(tool, "name", getattr(tool, "__name__", "")): tool for tool in build_tools(state)}

    read = _read(state, f"evidence://{first}")

    assert set(tools["read"].args) == {"path_id"}
    assert read["ok"] is True
    assert read["kind"] == "paragraph"
    assert read["locator"] == f"evidence://{first}"
    assert "第一节第一段" in read["text"]
    assert "第一节第二段" not in read["text"]


def test_read_accepts_consecutive_sibling_range_locator():
    state = _multi_section_state()
    first = _paragraph_path_id_containing(state, "第一节第一段")
    third = _paragraph_path_id_containing(state, "第一节第三段")

    read = _read(state, f"evidence://range/{first}/{third}")

    assert read["ok"] is True
    assert read["kind"] == "read_range"
    assert read["range_start"] == first
    assert read["range_end"] == third
    assert read["returned_path_ids"] == [
        first,
        _paragraph_path_id_containing(state, "第一节第二段"),
        third,
    ]
    assert "第一节第一段" in read["text"]
    assert "第一节第二段" in read["text"]
    assert "第一节第三段" in read["text"]
    assert "第一节第四段" not in read["text"]


def test_read_rejects_range_across_sections():
    state = _multi_section_state()
    first = _paragraph_path_id_containing(state, "第一节第一段")
    other_section = _paragraph_path_id_containing(state, "第二节第一段")

    read = _read(state, f"evidence://range/{first}/{other_section}")

    assert read["ok"] is False
    assert "direct siblings" in read["errors"][0]["message"]


def test_add_candidate_evidence_accepts_one_explicit_path_id_and_review_expands_inline():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    missing_path = _add_candidate_evidence(state, "founded_year")
    founded_bound = _add_candidate_evidence(state, "founded_year", path_id=locators["paragraph"])
    missing_bound = _add_candidate_evidence(state, "missing_required", path_id=locators["paragraph"])
    review = _review_evidences(state, "founded_year")

    assert missing_path["ok"] is False
    assert missing_path["errors"][0]["code"] == "CANDIDATE_PATH_REQUIRED"
    assert founded_bound["ok"] is True
    assert founded_bound["field_id"] == "founded_year"
    assert founded_bound["candidate_evidence"] == [locators["paragraph"]]
    assert missing_bound["ok"] is True
    assert missing_bound["field_id"] == "missing_required"
    assert missing_bound["candidate_evidence"] == [locators["paragraph"]]
    assert state.evidence_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert state.evidence_states["missing_required"]["evidence"] == [{"path_id": path_ids["paragraph"]}]
    assert review["candidate_evidence"] == [locators["paragraph"]]
    assert review["evidence"] == [f"{locators['paragraph']}/S001", f"{locators['paragraph']}/S002"]
    assert review["evidence_texts"] == [
        {"locator": f"{locators['paragraph']}/S001", "selector": "S001", "text": "公司成立于2020年。"},
        {"locator": f"{locators['paragraph']}/S002", "selector": "S002", "text": "总部位于上海。"},
    ]


def test_add_candidate_evidence_can_add_after_other_tools_with_explicit_path_id():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    _read(state, locators["paragraph"])
    _tree(state, "", depth=1)
    bound = _add_candidate_evidence(state, "deposit", path_id=locators["paragraph"])

    assert bound["ok"] is True
    assert state.evidence_states["deposit"]["evidence"] == [{"path_id": path_ids["paragraph"]}]


def test_list_and_table_read_return_all_rows_and_review_expands_all_inline():
    state = _large_collection_state()
    paths = _large_paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    list_result = _read(state, locators["list"])
    _add_candidate_evidence(state, "items", path_id=locators["list"])
    list_review = _review_evidences(state, "items")
    _read(state, locators["table"])
    _add_candidate_evidence(state, "fees", path_id=locators["table"])
    table_review = _review_evidences(state, "fees")

    assert list_result["has_more"] is False
    assert "[I035] 服务项目 35" in list_result["text"]
    assert list_review["evidence"] == [f"{locators['list']}/I{index:03d}" for index in range(1, 36)]
    assert "| R035 | 费用 35 | 35 |" in state.document.read_markdown(paths["table"], limit=0)["text"]
    assert table_review["evidence"] == [f"{locators['table']}/R{index:03d}" for index in range(1, 36)]


def test_write_field_requires_reviewed_inline_evidence_not_block_evidence():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    _read(state, locators["paragraph"])
    _add_candidate_evidence(state, "founded_year", path_id=locators["paragraph"])
    blocked_before_review = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )
    _review_evidences(state, "founded_year")
    blocked_block_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[locators["paragraph"]],
        status="resolved",
    )

    assert blocked_before_review["ok"] is False
    assert blocked_before_review["errors"][0]["code"] == "UNREVIEWED_FINAL_EVIDENCE"
    assert blocked_block_evidence["ok"] is False
    assert blocked_block_evidence["errors"][0]["code"] == "INLINE_FINAL_EVIDENCE_REQUIRED"
    _review_evidences(state, "founded_year")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )
    assert written["ok"] is True
    assert written["field"]["evidence"] == [f"{locators['paragraph']}/S001"]
    assert state.field_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001"]}]
    assert written["field"]["evidence_texts"] == [
        {"locator": f"{locators['paragraph']}/S001", "selector": "S001", "text": "公司成立于2020年。"}
    ]
    _review_evidences(state, "founded_year")
    blocked_unreviewed_inline = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S999"],
        status="resolved",
    )
    assert blocked_unreviewed_inline["ok"] is False
    assert blocked_unreviewed_inline["errors"][0]["code"] == "UNREVIEWED_FINAL_EVIDENCE"


def test_write_field_accepts_recent_review_snapshot_but_rejects_unreviewed_fields():
    reviewed_state = _state()
    paths = _paths()
    path_ids = _path_ids(reviewed_state, paths)
    locators = _locators(reviewed_state, paths)

    _read(reviewed_state, locators["paragraph"])
    _add_candidate_evidence(reviewed_state, "founded_year", path_id=locators["paragraph"])
    _review_evidences(reviewed_state, "founded_year")
    _read(reviewed_state, locators["list"])
    reviewed_write = _write_field(
        reviewed_state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )

    wrong_field_state = _state()
    wrong_paths = _path_ids(wrong_field_state, _paths())
    wrong_locators = _locators(wrong_field_state, _paths())
    _read(wrong_field_state, wrong_locators["paragraph"])
    _add_candidate_evidence(wrong_field_state, "founded_year", path_id=wrong_locators["paragraph"])
    _review_evidences(wrong_field_state, "founded_year")
    wrong_field_write = _write_field(
        wrong_field_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
    )

    assert reviewed_write["ok"] is True
    assert wrong_field_write["ok"] is False
    assert wrong_field_write["errors"][0]["code"] == "REVIEW_REQUIRED"

    failed_review_state = _state()
    failed_paths = _path_ids(failed_review_state, _paths())
    failed_locators = _locators(failed_review_state, _paths())
    _read(failed_review_state, failed_locators["paragraph"])
    _add_candidate_evidence(failed_review_state, "founded_year", path_id=failed_locators["paragraph"])
    _review_evidences(failed_review_state, "founded_year")
    failed_review = _review_evidences(failed_review_state, "unknown")
    write_after_failed_review = _write_field(
        failed_review_state,
        "founded_year",
        2020,
        final_evidence=[f"{failed_locators['paragraph']}/S001"],
        status="resolved",
    )

    assert failed_review["ok"] is False
    assert write_after_failed_review["ok"] is True


def test_add_candidate_after_review_invalidates_review_snapshot_for_that_field():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    _add_candidate_evidence(state, "founded_year", path_id=locators["paragraph"])
    _review_evidences(state, "founded_year")
    _add_candidate_evidence(state, "founded_year", path_id=locators["list"])
    stale_write = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )

    assert stale_write["ok"] is False
    assert stale_write["errors"][0]["code"] == "UNREVIEWED_FINAL_EVIDENCE"


def test_missing_and_null_enum_values_can_use_empty_evidence_after_review():
    missing_state = _state()
    enum_state = _enum_state()

    blocked_missing = _write_field(
        missing_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
    )
    _review_evidences(missing_state, "missing_required")
    missing = _write_field(
        missing_state,
        "missing_required",
        None,
        final_evidence=[],
        status="missing",
    )
    blocked_null_enum = _write_field(
        enum_state,
        "limited_use_decision",
        {"variant": "NotMentioned", "value": None},
        final_evidence=[],
        status="resolved",
    )
    _review_evidences(enum_state, "limited_use_decision")
    null_enum = _write_field(
        enum_state,
        "limited_use_decision",
        {"variant": "NotMentioned", "value": None},
        final_evidence=[],
        status="resolved",
    )

    assert blocked_missing["ok"] is False
    assert blocked_missing["errors"][0]["code"] == "REVIEW_REQUIRED"
    assert missing["ok"] is True
    assert blocked_null_enum["ok"] is False
    assert blocked_null_enum["errors"][0]["code"] == "REVIEW_REQUIRED"
    assert null_enum["ok"] is True


def test_write_field_normalizes_enum_value_json_string_from_tool_call():
    state = _enum_state()

    _review_evidences(state, "limited_use_decision")
    written = _write_field(
        state,
        "limited_use_decision",
        '{"variant": "NotMentioned", "value": null}',
        final_evidence=[],
        status="resolved",
    )

    assert written["ok"] is True
    assert written["field"]["value"] == {"variant": "NotMentioned", "value": None}
    assert state.field_states["limited_use_decision"]["value"] == {
        "variant": "NotMentioned",
        "value": None,
    }


def test_submit_result_requires_final_evidence_for_resolved_non_null_values():
    state = _enum_state()
    paragraph_path_id = _first_path_by_kind(state, "paragraph")
    paragraph_locator = f"evidence://{paragraph_path_id}"

    blocked_before_review = _write_field(
        state,
        "limited_use_decision",
        {"variant": "Entailment", "value": ["接收方只能为项目目的使用保密信息。"]},
        final_evidence=[],
        status="resolved",
    )
    _read(state, paragraph_locator)
    _add_candidate_evidence(state, "limited_use_decision", path_id=paragraph_locator)
    _review_evidences(state, "limited_use_decision")
    written = _write_field(
        state,
        "limited_use_decision",
        {"variant": "Entailment", "value": ["接收方只能为项目目的使用保密信息。"]},
        final_evidence=[],
        status="resolved",
    )
    blocked = _submit_result(state)

    assert blocked_before_review["ok"] is False
    assert blocked_before_review["errors"][0]["code"] == "REVIEW_REQUIRED"
    assert written["ok"] is True
    assert blocked["ok"] is False
    assert blocked["errors"][0]["code"] == "MISSING_FINAL_EVIDENCE"


def test_read_write_reject_raw_paths_and_bare_ids_and_use_evidence_links_through_review():
    state = _state()
    paths = _paths()
    path_ids = _path_ids(state, paths)
    locators = _locators(state, paths)

    raw_path_result = _read(state, paths["paragraph"])
    bare_path_id_result = _read(state, path_ids["paragraph"])
    read_result = _read(state, locators["paragraph"])
    _add_candidate_evidence(state, "founded_year", path_id=locators["paragraph"])
    review = _review_evidences(state, "founded_year")
    written = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[f"{locators['paragraph']}/S001"],
        status="resolved",
    )
    raw_path_final_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[paths["paragraph"]],
        status="resolved",
    )

    assert raw_path_result["ok"] is False
    assert bare_path_id_result["ok"] is False
    assert read_result["locator"] == locators["paragraph"]
    assert review["candidate_evidence"] == [locators["paragraph"]]
    assert written["ok"] is True
    assert written["field"]["evidence"] == [f"{locators['paragraph']}/S001"]
    assert state.field_states["founded_year"]["evidence"] == [{"path_id": path_ids["paragraph"], "sentences": ["S001"]}]
    _review_evidences(state, "founded_year")
    raw_path_final_evidence = _write_field(
        state,
        "founded_year",
        2020,
        final_evidence=[paths["paragraph"]],
        status="resolved",
    )
    assert raw_path_final_evidence["ok"] is False
    assert raw_path_final_evidence["errors"][0]["code"] == "BAD_FINAL_EVIDENCE_LOCATOR"
