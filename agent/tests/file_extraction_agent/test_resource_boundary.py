"""磁盘资源作为生成端与问答工具之间的唯一业务交接。"""

import ast
from pathlib import Path

import pytest

from service.file_extraction_agent.core.graph import build_graph_state
from service.file_extraction_agent.schemas import DocumentQaMessage


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


def test_graph_state_only_carries_execution_inputs(resource_path):
    state = build_graph_state(resource_path=resource_path,
                              messages=[DocumentQaMessage(role="user", content="问题")])
    assert set(vars(state)) == {"resource_path", "messages", "run_options"}
    assert state.resource_path == resource_path


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
