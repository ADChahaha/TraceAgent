from __future__ import annotations

import inspect

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    __all__ as html_tools_all,
    _grep,
    _inspect,
    _read,
    _tree,
    build_tools,
)
from service.file_extraction_agent.input_adapter import build_completion_input


def _state():
    completion_input = build_completion_input(
        completion_id="cmp_123",
        documents=[
            {
                "filename": "contract.html",
                "html": """
                <h1 id="title">服务合同</h1>
                <h2 id="term">Term</h2>
                <p id="p1">Either party may terminate this Agreement with 30 days written notice.</p>
                <ul id="list1">
                  <li id="li1">Services include system maintenance.</li>
                  <li id="li2">Services include data backup.</li>
                </ul>
                <table id="table1">
                  <caption id="cap1">Fees</caption>
                  <tr id="tr0"><th>Item</th><th>Amount</th></tr>
                  <tr id="tr1"><td>Service fee</td><td>1000</td></tr>
                  <tr id="tr2"><td>Deposit</td><td>500</td></tr>
                </table>
                <h2 id="notice">Notice</h2>
                <p id="p2">All notices must be delivered by email or courier.</p>
                """,
            }
        ],
        messages=[{"role": "user", "content": "Can the contract be terminated early?"}],
    )
    return build_graph_state(completion_input)


def _multi_section_state():
    completion_input = build_completion_input(
        completion_id="cmp_123",
        documents=[
            {
                "filename": "sections.html",
                "html": """
                <h1>连续阅读</h1>
                <h2>第一节</h2>
                <p>第一节第一段。</p>
                <p>第一节第二段。</p>
                <p>第一节第三段。</p>
                <h2>第二节</h2>
                <p>第二节第一段。</p>
                """,
            }
        ],
        messages=[{"role": "user", "content": "总结第一节"}],
    )
    return build_graph_state(completion_input)


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


def test_build_tools_exposes_qa_navigation_tools_only():
    tools = build_tools(_state())
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == ["tree", "grep", "read", "inspect"]


def test_module_exports_qa_helpers_only():
    assert "_tree" in html_tools_all
    assert "_grep" in html_tools_all
    assert "_read" in html_tools_all
    assert "_inspect" in html_tools_all
    assert "_add_candidate_evidence" not in html_tools_all
    assert "_review_evidences" not in html_tools_all
    assert "_write_field" not in html_tools_all
    assert "_submit_result" not in html_tools_all


def test_internal_tool_helpers_do_not_accept_reason_parameter():
    for helper in (_tree, _grep, _read, _inspect):
        assert "reason" not in inspect.signature(helper).parameters


def test_tree_and_read_use_evidence_locators():
    state = _state()
    paragraph = _paragraph_path_id_containing(state, "Either party")

    tree = _tree(state, "", depth=2)
    read = _read(state, f"evidence://{paragraph}")
    raw_path_result = _read(state, paragraph)

    assert tree["ok"] is True
    assert "evidence://0001" in tree["text"]
    assert read["ok"] is True
    assert read["locator"] == f"evidence://{paragraph}"
    assert "30 days written notice" in read["text"]
    assert raw_path_result["ok"] is False
    assert raw_path_result["errors"][0]["code"] == "BAD_LOCATOR"


def test_grep_returns_candidate_blocks_but_not_inline_evidence():
    state = _state()

    result = _grep(state, query="terminate", scope="", max_results=5)

    assert result["ok"] is True
    assert result["query"] == "terminate"
    assert result["results"][0]["locator"].startswith("evidence://")
    assert result["results"][0]["kind"] == "paragraph"
    assert "terminate" in result["results"][0]["preview"].lower()
    assert "S001" not in result["results"][0]["locator"]


def test_grep_can_scope_to_section_locator():
    state = _state()
    term_section = state.document.path_id("/001-contract-服务合同/001-服务合同/001-Term")
    notice_section = state.document.path_id("/001-contract-服务合同/001-服务合同/002-Notice")

    term_result = _grep(state, query="notice", scope=f"evidence://{term_section}", max_results=5)
    notice_result = _grep(state, query="notice", scope=f"evidence://{notice_section}", max_results=5)

    assert term_result["ok"] is True
    assert [item["locator"] for item in term_result["results"]] == ["evidence://0001.0001.0001.0001"]
    assert notice_result["ok"] is True
    assert [item["locator"] for item in notice_result["results"]] == ["evidence://0001.0001.0002.0001"]


def test_read_accepts_consecutive_sibling_range_locator():
    state = _multi_section_state()
    first = _paragraph_path_id_containing(state, "第一节第一段")
    third = _paragraph_path_id_containing(state, "第一节第三段")

    read = _read(state, f"evidence://range/{first}/{third}")

    assert read["ok"] is True
    assert read["kind"] == "read_range"
    assert read["range_start"] == first
    assert read["range_end"] == third
    assert "第一节第一段" in read["text"]
    assert "第一节第二段" in read["text"]
    assert "第一节第三段" in read["text"]
    assert "第二节第一段" not in read["text"]


def test_inspect_expands_paragraph_list_and_table_to_inline_links():
    state = _state()
    paragraph = _paragraph_path_id_containing(state, "Either party")
    list_path = _first_path_by_kind(state, "list")
    table_path = _first_path_by_kind(state, "table")

    paragraph_result = _inspect(state, f"evidence://{paragraph}")
    list_result = _inspect(state, f"evidence://{list_path}")
    table_result = _inspect(state, f"evidence://{table_path}")

    assert paragraph_result["ok"] is True
    assert paragraph_result["evidence"] == [f"evidence://{paragraph}/S001"]
    assert paragraph_result["evidence_texts"] == [
        {
            "locator": f"evidence://{paragraph}/S001",
            "selector": "S001",
            "text": "Either party may terminate this Agreement with 30 days written notice.",
        }
    ]
    assert list_result["evidence"] == [
        f"evidence://{list_path}/I001",
        f"evidence://{list_path}/I002",
    ]
    assert table_result["evidence"] == [
        f"evidence://{table_path}/R001",
        f"evidence://{table_path}/R002",
    ]


def test_inspect_rejects_section_and_inline_locators():
    state = _state()
    section = state.document.path_id("/001-contract-服务合同/001-服务合同/001-Term")
    paragraph = _paragraph_path_id_containing(state, "Either party")

    section_result = _inspect(state, f"evidence://{section}")
    inline_result = _inspect(state, f"evidence://{paragraph}/S001")

    assert section_result["ok"] is False
    assert section_result["errors"][0]["code"] == "UNREADABLE_INSPECT_PATH"
    assert inline_result["ok"] is False
    assert inline_result["errors"][0]["code"] == "BAD_LOCATOR"
