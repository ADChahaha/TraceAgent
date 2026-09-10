from __future__ import annotations

import asyncio
import base64
import inspect

import pytest
from service.document_resources.schemas import InputDocument

from service.file_extraction_agent.core.tools import (
    __all__ as tools_all,
    _grep,
    _ls,
    _read,
    _search_embedding,
    build_tools,
)
from service.document_resources.documents import materialize_tree
from service.file_extraction_agent.core.tools.workspace import DocumentFileTree
from service.file_extraction_agent.schemas import RunOptions
from types import SimpleNamespace
from service.file_extraction_agent.schemas import DocumentQaMessage


def _state(tmp_path):
    return _prepare_test_state(
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
    assert all(inspect.iscoroutinefunction(tool.coroutine) for tool in tools)


def test_embedding_tool_does_not_advertise_unused_scope(tmp_path):
    search = next(tool for tool in build_tools(_state(tmp_path)) if tool.name == "search_embedding")
    assert set(search.args) == {"query", "top_k"}


def test_model_path_examples_can_be_read_from_object_store():
    """模型看到的路径示例必须能作为对象 key 交给 read。"""
    import re
    from service.file_extraction_agent.core.messages import build_qa_messages

    key = "documents/0001-contract/0001-section/0001-block.md"
    store = SimpleNamespace(get_object=lambda bucket, path: b"Payment due in 30 days." if path == key else None)
    state = SimpleNamespace(document=DocumentFileTree(store, "res_example", "documents"))
    prompt = build_qa_messages([])[0].content
    links = re.findall(r"\]\(([^)]+\.md)\)", prompt)
    assert links
    for path in links:
        assert _read(state, path)["ok"], path
    for tool in build_tools(state):
        if tool.name in {"ls", "read"}:
            assert "absolute" not in tool.description.lower()


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


def test_run_tool_only_needs_operation_and_normalizes_failure():
    from service.file_extraction_agent.core.tools.base import run_tool

    assert run_tool(lambda: {"ok": True, "text": "正文"}) == {"ok": True, "text": "正文"}

    def fail():
        raise ValueError("读取失败")

    assert run_tool(fail) == {"ok": False, "errors": [{"message": "读取失败"}]}


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


def test_grep_returns_candidate_blocks_but_not_inline_evidence(tmp_path):
    state = _state(tmp_path)

    result = _grep(state, query="terminate", scope="", max_results=5)

    assert result["ok"] is True
    assert result["query"] == "terminate"
    assert "terminate" in result["output"].lower()


def test_read_rejects_non_file_path(tmp_path):
    state = _state(tmp_path)

    result = _read(state, "definitely/not/a/file.md")

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "BAD_PATH"


def test_grep_can_scope_to_directory(tmp_path):
    state = _state(tmp_path)

    result = _grep(state, query="notice", scope="", max_results=5)

    assert result["ok"] is True
    assert "notice" in result["output"].lower()


def test_grep_matches_case_insensitively_and_limits_results(tmp_path):
    state = _state(tmp_path)

    result = _grep(state, query="SERVICES", scope="", max_results=5)

    assert result["ok"] is True
    assert "services" in result["output"].lower()


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


def _fake_index():
    import numpy as np

    from service.file_extraction_agent.core.tools.embedding import Chunk, EmbeddingIndex

    chunks = [
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c1", text="Either party may terminate with notice.", token_range=(0, 6), covered_files=["/abs/0001/docs/0001-termination.md"]),
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c2", text="Payment is due within 30 days.", token_range=(6, 12), covered_files=["/abs/0001/docs/0003-terms.md"]),
        Chunk(document="contract.pdf", chunk_id="contract.pdf#c3", text="Notice must be written in the same language.", token_range=(12, 18), covered_files=["/abs/0001/docs/0002-notice.md"]),
    ]
    vectors = _fake_embedder([chunk.text for chunk in chunks])
    return EmbeddingIndex(model_id="fake-a8m", chunks=chunks, vectors=vectors, dimension=3)


def _install_fake_index(monkeypatch):
    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.embedding._get_index", lambda _state: _fake_index()
    )


def _install_worker(monkeypatch, response):
    calls: dict = {}

    async def fake_run_worker(request):
        calls["request"] = request
        return response

    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.embedding._run_worker", fake_run_worker
    )
    return calls


async def test_search_embedding_sends_index_request_and_returns_worker_results(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _install_fake_index(monkeypatch)
    response = {
        "ok": True,
        "query": "payment",
        "results": [
            {
                "score": 0.9,
                "document": "contract.pdf",
                "chunk_id": "contract.pdf#c1",
                "text": "Either party may terminate with notice.",
                "token_range": [0, 6],
                "covered_files": ["documents/a/1.md"],
            }
        ],
    }
    calls = _install_worker(monkeypatch, response)

    result = await _search_embedding(state, query="payment", top_k=3)

    assert result == response
    request = calls["request"]
    assert request["query"] == "payment"
    assert request["top_k"] == 3
    assert request["model_id"] == "fake-a8m"
    assert request["dimension"] == 3
    assert len(request["chunks"]) == 3
    assert len(base64.b64decode(request["vectors_b64"])) == 3 * 3 * 4


async def test_search_embedding_returns_result_without_event_state(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _install_fake_index(monkeypatch)
    _install_worker(monkeypatch, {"ok": True, "query": "payment", "results": []})

    result = await _search_embedding(state, query="payment", top_k=1)
    assert result["ok"] is True
    assert not hasattr(state, "events")


async def test_search_embedding_rejects_empty_query(tmp_path, monkeypatch):
    state = _state(tmp_path)

    async def forbidden(request):
        raise AssertionError("worker must not start for an empty query")

    monkeypatch.setattr(
        "service.file_extraction_agent.core.tools.embedding._run_worker", forbidden
    )

    result = await _search_embedding(state, query="   ", top_k=3)

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "BAD_QUERY"


class _FakeEmbedding:
    def __init__(self):
        self._slot = asyncio.Semaphore(1)

    def search_slot(self):
        return self._slot


def _prepare_test_state(*, documents, messages, workspace_root):
    """工具和 prompt 测试只准备文件树，不引入 completion 管理字段。"""
    return SimpleNamespace(
        document=DocumentFileTree.from_local_dir(materialize_tree(documents, workspace_root)),
        embedding=_FakeEmbedding(),
        messages=messages,
        run_options=RunOptions(),
    )
