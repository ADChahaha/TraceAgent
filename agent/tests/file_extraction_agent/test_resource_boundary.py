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


def test_graph_only_keeps_messages_with_options_bound_outside():
    from service.file_extraction_agent.core.graph import build_qa_graph
    from service.file_extraction_agent.core.messages import build_qa_messages
    from service.file_extraction_agent.core.model_invocation import _invoke_model_message
    from service.file_extraction_agent.core.executor import _execute_tools_parallel
    from unittest.mock import Mock
    from langchain_core.messages import AIMessage
    from service.file_extraction_agent.core.model import ChatModelFallbackChain, ModelCallAttempt

    provider = Mock(spec=["bind_tools", "invoke"])
    provider.bind_tools.return_value = provider
    provider.invoke.return_value = AIMessage(content="回答", response_metadata={"finish_reason": "stop"})
    model = ChatModelFallbackChain([ModelCallAttempt("test", provider, False)])
    graph = build_qa_graph(model, [], run_options=RunOptions(tool_execution_timeout=0.1),
                           invoke_model=_invoke_model_message, execute_tools=_execute_tools_parallel)
    messages = build_qa_messages([DocumentQaMessage(role="user", content="问题")])
    result = graph.invoke({"messages": messages})
    assert set(result) == {"messages"}
    assert [message.content for message in result["messages"]][-2:] == ["问题", "回答"]


def test_tools_read_prepared_files_without_builder(resource_path, monkeypatch):
    from service import document_resources
    from service.file_extraction_agent.core.tools import workspace, _ls, _read

    def forbidden(*args, **kwargs):
        raise AssertionError("问答工具不能调用资源生成端")

    monkeypatch.setattr(document_resources, "prepare_resources", forbidden)
    if hasattr(document_resources, "load_resource"):
        monkeypatch.setattr(document_resources, "load_resource", forbidden)
    context = workspace.open_workspace(resource_path)
    listing = _ls(context)
    assert listing["ok"]
    assert [entry["name"] for entry in listing["entries"]] == ["001-contract-合同"]
    path = next((Path(resource_path) / "documents").rglob("*.md"))
    assert "terminate" in _read(context, str(path))["text"]
    assert not _read(context, str(Path(resource_path) / "manifest.json"))["ok"]


@pytest.mark.parametrize("damage", ["version", "vectors", "reference"])
def test_tool_preflight_rejects_damaged_resource(resource_path, damage):
    import json
    import numpy as np
    from service.file_extraction_agent.core.tools.workspace import validate_resource

    path = Path(resource_path)
    if damage == "version":
        manifest = path / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = -1
        manifest.write_text(json.dumps(data), encoding="utf-8")
    elif damage == "vectors":
        np.save(path / "index" / "vectors.npy", np.array([[float("nan")]]))
    else:
        index = path / "index" / "index.json"
        data = json.loads(index.read_text(encoding="utf-8"))
        data["chunks"][0]["covered_files"] = ["../../outside.md"]
        index.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_resource(resource_path)
