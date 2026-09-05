from __future__ import annotations

import inspect

import pytest

from service.file_extraction_agent.core.tools import (
    __all__ as tools_all,
    _grep,
    _ls,
    _read,
    _search_embedding,
    build_tools,
)
from service.file_extraction_agent.manager import prepare_completion_state
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument


def _state(tmp_path):
    return prepare_completion_state(
        completion_id="cmp_123",
        documents=[
            InputDocument(
                filename="contract.html",
                html="""
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
            )
        ],
        messages=[DocumentQaMessage(role="user", content="Can the contract be terminated early?")],
        workspace_root=tmp_path,
    )


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

    assert tool_names == ["ls", "grep", "read", "search_embedding"]


def test_module_exports_qa_helpers_only():
    assert "_ls" in tools_all
    assert "_tree" not in tools_all
    assert "_grep" in tools_all
    assert "_read" in tools_all
    assert "_inspect" not in tools_all
    assert "_add_candidate_evidence" not in tools_all
    assert "_review_evidences" not in tools_all
    assert "_write_field" not in tools_all
    assert "_submit_result" not in tools_all


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
        "service.file_extraction_agent.core.tools.grep._run_ripgrep",
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
        "service.file_extraction_agent.core.tools.grep._run_ripgrep",
        lambda query, scope_dir, max_results: "001-section.md:notice\n",
    )

    result = _grep(state, query="notice", scope=term_dir, max_results=5)

    assert result["ok"] is True
    assert "notice" in result["output"].lower()


def test_grep_fails_gracefully_when_ripgrep_missing(tmp_path, monkeypatch):
    state = _state(tmp_path)
    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.grep._run_ripgrep", lambda *a, **k: None
    )

    result = _grep(state, query="terminate", scope="", max_results=5)

    assert result["ok"] is False


def _add_files_to(state, extra):
    from pathlib import Path

    doc_dir = next((e.path for e in state.document.entries() if e.kind == "dir"), None)
    base = Path(doc_dir)
    for name, text in extra:
        (base / name).write_text(text, encoding="utf-8")


def _fake_embedder(texts):
    import numpy as np

    rows = []
    for text in texts:
        n = sum(ord(ch) for ch in text) or 1
        rows.append([float(n % 2), float(len(text) % 3), float(n % 5)])
    return np.array(rows, dtype=np.float32)


class _FakeEmbedder:
    dim = 3

    def encode(self, texts):
        return _fake_embedder(texts)


def _fake_index():
    import numpy as np

    from service.file_extraction_agent.core.tools.embedding.search import Chunk, EmbeddingIndex

    chunks = [
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c1", text="Either party may terminate with notice.", token_range=(0, 6), covered_files=["/abs/0001/docs/0001-termination.md"]),
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c2", text="Payment is due within 30 days.", token_range=(6, 12), covered_files=["/abs/0001/docs/0003-terms.md"]),
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c3", text="Notice must be written in the same language.", token_range=(12, 18), covered_files=["/abs/0001/docs/0002-notice.md"]),
    ]
    vectors = _fake_embedder([chunk.text for chunk in chunks])
    return EmbeddingIndex(model_id="fake-a8m", chunks=chunks, vectors=vectors, dimension=3)


def _install_fake_index(monkeypatch):
    fake_embedder = _FakeEmbedder()

    def fake_get_index(state, embedder, scope=""):
        return _fake_index()

    monkeypatch.setattr("service.file_extraction_agent.core.tools.embedding._get_index", fake_get_index)
    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.embedding._get_embedder", lambda state: fake_embedder
    )


def test_search_embedding_returns_text_and_covered_files_sorted(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _install_fake_index(monkeypatch)

    result = _search_embedding(state, query="payment", top_k=3, scope="")

    assert result["ok"] is True
    assert result["query"] == "payment"
    assert len(result["results"]) == 3
    assert result["results"][0]["score"] >= result["results"][-1]["score"]
    for item in result["results"]:
        assert item["text"]
        assert item["document"]
        assert item["covered_files"]
        assert item["chunk_id"]


def test_search_embedding_returns_result_without_event_state(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _install_fake_index(monkeypatch)

    result = _search_embedding(state, query="payment", top_k=1, scope="")
    assert result["ok"] is True
    assert not hasattr(state, "events")


def test_search_embedding_rejects_empty_query(tmp_path, monkeypatch):
    state = _state(tmp_path)
    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.embedding._get_embedder", lambda state: _fake_embedder
    )

    result = _search_embedding(state, query="   ", top_k=3, scope="")

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "BAD_QUERY"
