"""磁盘资源作为生成端与问答工具之间的唯一业务交接。"""

import ast
from pathlib import Path

import pytest

from service.file_extraction_agent.schemas import DocumentQaMessage, RunOptions


def test_qa_package_does_not_import_resource_builder():
    root = Path(__file__).resolve().parents[2] / "service" / "file_extraction_agent"
    dependencies = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            dependencies.extend((str(path.relative_to(root)), name) for name in names
                                if name.startswith("service.document_resources"))
    assert dependencies == []


async def test_graph_keeps_retry_state_with_options_bound_outside():
    from service.file_extraction_agent.core.graph import build_qa_graph
    from service.file_extraction_agent.core.messages import build_qa_messages
    from service.file_extraction_agent.core.model_invocation import _invoke_model_message
    from service.file_extraction_agent.core.executor import _execute_tools_parallel
    from unittest.mock import Mock, AsyncMock
    from langchain_core.messages import AIMessage
    from service.file_extraction_agent.core.model import ConfiguredChatModel

    provider = Mock(spec=["bind_tools", "ainvoke"])
    provider.bind_tools.return_value = provider
    provider.ainvoke = AsyncMock()
    provider.ainvoke.return_value = AIMessage(content="回答", response_metadata={"finish_reason": "stop"})
    model = ConfiguredChatModel(provider, use_stream=False)
    graph = build_qa_graph(model, [], run_options=RunOptions(tool_execution_timeout=0.1),
                           invoke_model=_invoke_model_message, execute_tools=_execute_tools_parallel)
    messages = build_qa_messages([DocumentQaMessage(role="user", content="问题")])
    result = await graph.ainvoke({"messages": messages})
    assert set(result) == {"messages", "model_attempt", "model_failure", "retry_delay_seconds"}
    assert result["model_attempt"] == 0 and result["model_failure"] is None
    assert [message.content for message in result["messages"]][-2:] == ["问题", "回答"]


def test_tools_read_prepared_files_without_builder(resource_path, monkeypatch):
    from service import document_resources
    from service.file_extraction_agent.core.tools import _ls, _read, worker
    from service.file_extraction_agent.core.tools.workspace import document_tree_from_payload

    def forbidden(*args, **kwargs):
        raise AssertionError("问答工具不能调用资源生成端")

    monkeypatch.setattr(document_resources, "prepare_resources", forbidden)
    if hasattr(document_resources, "load_resource"):
        monkeypatch.setattr(document_resources, "load_resource", forbidden)
    refs = [{"type": ref.type, "location": ref.location} for ref in resource_path]
    payload = worker.handle({"operation": "prepare", "args": {"resource_path": refs}})["workspace"]
    context = workspace_from_payload(document_tree_from_payload(payload))
    listing = _ls(context)
    assert listing["ok"]
    assert [entry["name"] for entry in listing["entries"]] == ["001-contract-合同"]
    md_key = next(e.path for e in _all_md(context))
    assert "terminate" in _read(context, md_key)["text"]
    assert not _read(context, "manifest.json")["ok"]


def workspace_from_payload(tree):
    from types import SimpleNamespace

    return SimpleNamespace(document=tree)


def _all_md(context):
    result = []

    def collect(prefix):
        for entry in context.document.entries(prefix):
            if entry.kind == "dir":
                collect(entry.path)
            else:
                result.append(entry)

    for top in context.document.entries():
        if top.kind == "dir":
            collect(top.path)
    return result


@pytest.mark.parametrize("damage", ["version", "vectors", "reference"])
def test_tool_preflight_rejects_damaged_resource(resource_path, s3_store, damage):
    import json

    from tests.conftest import resource_bucket
    from service.file_extraction_agent.core.tools import worker

    bucket = resource_bucket(resource_path)
    if damage == "version":
        manifest = json.loads(s3_store.get_object(bucket, "manifest.json").decode("utf-8"))
        manifest["version"] = -1
        s3_store.put_object(bucket, "manifest.json", json.dumps(manifest).encode("utf-8"))
    elif damage == "vectors":
        s3_store.put_object(bucket, "index/vectors.npy", b"corrupt")
    else:
        index = json.loads(s3_store.get_object(bucket, "index/index.json").decode("utf-8"))
        index["chunks"][0]["covered_files"] = ["../../outside.md"]
        s3_store.put_object(bucket, "index/index.json", json.dumps(index).encode("utf-8"))
    refs = [{"type": ref.type, "location": ref.location} for ref in resource_path]
    response = worker.handle({"operation": "prepare", "args": {"resource_path": refs}})
    assert response["ok"] is False
    assert response["kind"] == "invalid"
