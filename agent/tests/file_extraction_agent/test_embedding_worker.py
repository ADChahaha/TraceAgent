"""统一 worker：operation 分发、请求校验、prepare/ls/read 及真实子进程入口。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from service.document_resources.model import DEFAULT_EMBEDDING_MODEL
from service.file_extraction_agent.core.tools import worker
from service.file_extraction_agent.core.tools.workspace import (
    document_tree_from_payload,
    load_workspace_payload,
)

AGENT_ROOT = Path(__file__).resolve().parents[2]


class _FakeEmbedder:
    def __init__(self, model_id: str):
        self.model_id = model_id

    def encode(self, texts):
        return np.asarray([[1.0, 0.0]], dtype=np.float32)


def _chunk(index: int) -> dict:
    return {
        "document": "doc",
        "chunk_id": f"c{index}",
        "text": f"text {index}",
        "token_range": [0, 1],
        "char_range": [0, 1],
        "covered_files": [f"documents/a/{index}.md"],
    }


def _index(dimension: int = 2, model_id: str = "m") -> dict:
    vectors = np.asarray(
        [[1.0, 0.0], [0.0, 1.0], [0.70710678, 0.70710678]], dtype=np.float32
    )
    return {
        "model_id": model_id,
        "dimension": dimension,
        "chunks": [_chunk(1), _chunk(2), _chunk(3)],
        "vectors_b64": base64.b64encode(vectors.tobytes()).decode(),
    }


def _search_request(**overrides) -> dict:
    request = {
        "operation": "search_embedding",
        "args": {"query": "付款期限", "top_k": 2},
        "workspace": {"index": _index()},
    }
    request.update(overrides)
    return request


def test_handle_rejects_unknown_operation():
    response = worker.handle({"operation": "nope", "args": {}})

    assert response["ok"] is False
    assert "unknown operation" in response["errors"][0]["message"]


def test_search_returns_top_k_with_fields(monkeypatch):
    monkeypatch.setattr(worker, "_embedder_class", lambda: _FakeEmbedder)

    response = worker.handle(_search_request())

    assert response["ok"] is True
    assert [item["chunk_id"] for item in response["results"]] == ["c1", "c3"]
    assert response["results"][0]["covered_files"] == ["documents/a/1.md"]
    assert response["results"][0]["token_range"] == [0, 1]
    assert response["results"][0]["score"] > response["results"][1]["score"]


def test_search_rejects_bad_vectors(monkeypatch):
    monkeypatch.setattr(worker, "_embedder_class", lambda: _FakeEmbedder)
    bad = _index()
    bad["vectors_b64"] = base64.b64encode(b"x").decode()

    response = worker.handle(_search_request(workspace={"index": bad}))

    assert response["ok"] is False
    assert "vectors" in response["errors"][0]["message"]


def test_search_rejects_empty_query(monkeypatch):
    monkeypatch.setattr(worker, "_embedder_class", lambda: _FakeEmbedder)

    response = worker.handle(_search_request(args={"query": "   ", "top_k": 2}))

    assert response["ok"] is False


def test_prepare_returns_workspace_payload(resource_path):
    refs = [{"type": ref.type, "location": ref.location} for ref in resource_path]

    response = worker.handle({"operation": "prepare", "args": {"resource_path": refs}})

    assert response["ok"] is True
    assert response["workspace"]["bucket"]
    assert response["workspace"]["documents_archive_b64"]
    assert response["workspace"]["index"]["dimension"] > 0
    assert all(
        path.startswith("documents/")
        for chunk in response["workspace"]["index"]["chunks"]
        for path in chunk["covered_files"]
    )


def test_prepare_rejects_missing_locations():
    response = worker.handle({"operation": "prepare", "args": {"resource_path": []}})

    assert response["ok"] is False
    assert response["kind"] == "invalid"


def test_handle_reads_from_workspace_payload(resource_path):
    payload = load_workspace_payload(resource_path)
    tree = document_tree_from_payload(payload)

    listing = worker.handle({"operation": "ls", "args": {"path": ""}, "workspace": payload})
    assert listing["ok"] is True
    md_key = _first_md_key(tree)
    read = worker.handle({"operation": "read", "args": {"path": md_key}, "workspace": payload})
    assert read["ok"] is True
    assert "terminate" in read["text"]


def _first_md_key(tree) -> str:
    for entry in tree.entries():
        if entry.kind == "dir":
            nested = _first_md_key_in(tree, entry.path)
            if nested:
                return nested
    raise AssertionError("missing markdown entry")


def _first_md_key_in(tree, prefix: str) -> str | None:
    for entry in tree.entries(prefix):
        if entry.kind == "dir":
            nested = _first_md_key_in(tree, entry.path)
            if nested:
                return nested
        elif entry.kind == "md":
            return entry.path
    return None


def test_worker_subprocess_entry_with_real_model(monkeypatch):
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("embedding model is not cached locally")

    vectors = np.eye(384, dtype=np.float32)[:3]
    request = {
        "operation": "search_embedding",
        "args": {"query": "付款期限", "top_k": 3},
        "workspace": {
            "index": {
                "model_id": DEFAULT_EMBEDDING_MODEL,
                "dimension": 384,
                "chunks": [_chunk(1), _chunk(2), _chunk(3)],
                "vectors_b64": base64.b64encode(vectors.tobytes()).decode(),
            }
        },
    }
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}

    result = subprocess.run(
        [sys.executable, "-m", "service.file_extraction_agent.core.tools.worker"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=AGENT_ROOT,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["ok"] is True
    assert len(response["results"]) == 3
