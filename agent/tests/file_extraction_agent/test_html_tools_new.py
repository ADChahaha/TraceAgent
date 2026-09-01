from __future__ import annotations

import inspect

import pytest

from service.file_extraction_agent.impl.html_state import build_graph_state
from service.file_extraction_agent.impl.html_tools import (
    __all__ as html_tools_all,
    _grep,
    _ls,
    _read,
    build_tools,
)
from service.file_extraction_agent.input_adapter import build_completion_input


def _state(tmp_path):
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
                <h2 id="notice">Notice</h2>
                <p id="p2">All notices must be delivered by email or courier.</p>
                """,
            }
        ],
        messages=[{"role": "user", "content": "Can the contract be terminated early?"}],
        workspace_root=tmp_path,
    )
    return build_graph_state(completion_input)


def _all_md_entries(state):
    result = []

    def collect(dir_path):
        for entry in state.document.entries(dir_path):
            if entry.kind == "dir":
                collect(entry.path)
            else:
                result.append(entry)

    for top in state.document.entries():
        if top.kind == "dir":
            collect(top.path)
    return result


def _paragraph_path_containing(state, text):
    for entry in _all_md_entries(state):
        if text in state.document.read(entry.path):
            return entry.path
    raise AssertionError(f"missing paragraph containing {text}")


def test_build_tools_exposes_qa_navigation_tools_only(tmp_path):
    tools = build_tools(_state(tmp_path))
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]

    assert tool_names == ["ls", "grep", "read"]


def test_module_exports_qa_helpers_only():
    assert "_ls" in html_tools_all
    assert "_tree" not in html_tools_all
    assert "_grep" in html_tools_all
    assert "_read" in html_tools_all
    assert "_inspect" not in html_tools_all
    assert "_add_candidate_evidence" not in html_tools_all
    assert "_review_evidences" not in html_tools_all
    assert "_write_field" not in html_tools_all
    assert "_submit_result" not in html_tools_all


def test_internal_tool_helpers_do_not_accept_reason_parameter(tmp_path):
    for helper in (_ls, _grep, _read):
        assert "reason" not in inspect.signature(helper).parameters


def test_ls_and_read_use_real_file_paths(tmp_path):
    state = _state(tmp_path)
    paragraph = _paragraph_path_containing(state, "Either party")

    listing = _ls(state, "")
    read = _read(state, paragraph)

    assert listing["ok"] is True
    assert listing["text"] != ""
    assert read["ok"] is True
    assert "30 days written notice" in read["text"]


def test_ls_lists_only_the_current_tree_level(tmp_path):
    state = _state(tmp_path)

    document_dir = next(e for e in state.document.entries() if e.kind == "dir")
    document_listing = _ls(state, document_dir.path)

    assert document_listing["ok"] is True
    assert document_listing["text"] != ""
    assert "terminate" not in document_listing["text"]


def test_grep_returns_candidate_blocks_but_not_inline_evidence(tmp_path, monkeypatch):
    state = _state(tmp_path)
    monkeypatch.setattr(
        "service.file_extraction_agent.impl.html_tools._run_ripgrep",
        lambda query, scope_dir, max_results: "001-something.md:Either party may terminate\n",
    )

    result = _grep(state, query="terminate", scope="", max_results=5)

    assert result["ok"] is True
    assert result["query"] == "terminate"
    assert "terminate" in result["output"].lower()


def test_read_rejects_non_file_path(tmp_path):
    state = _state(tmp_path)

    result = _read(state, "/definitely/not/a/file.md")

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "BAD_PATH"


def test_grep_can_scope_to_directory(tmp_path, monkeypatch):
    state = _state(tmp_path)
    term_dir = next(
        e.path
        for e in state.document.entries()
        if e.kind == "dir"
        for sub in state.document.entries(e.path)
        if sub.kind == "dir"
    )
    monkeypatch.setattr(
        "service.file_extraction_agent.impl.html_tools._run_ripgrep",
        lambda query, scope_dir, max_results: "001-section.md:notice\n",
    )

    result = _grep(state, query="notice", scope=term_dir, max_results=5)

    assert result["ok"] is True
    assert "notice" in result["output"].lower()


def test_grep_fails_gracefully_when_ripgrep_missing(tmp_path, monkeypatch):
    state = _state(tmp_path)
    monkeypatch.setattr("service.file_extraction_agent.impl.html_tools._run_ripgrep", lambda *a, **k: None)

    result = _grep(state, query="terminate", scope="", max_results=5)

    assert result["ok"] is False
