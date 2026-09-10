"""检索 worker：请求校验、top-k 输出，以及真实子进程入口。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openvino")

from service.document_resources.model import DEFAULT_EMBEDDING_MODEL
from service.file_extraction_agent.core.tools import worker

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


def _request(**overrides) -> dict:
    vectors = np.asarray(
        [[1.0, 0.0], [0.0, 1.0], [0.70710678, 0.70710678]], dtype=np.float32
    )
    request = {
        "query": "付款期限",
        "top_k": 2,
        "model_id": "m",
        "dimension": 2,
        "chunks": [_chunk(1), _chunk(2), _chunk(3)],
        "vectors_b64": base64.b64encode(vectors.tobytes()).decode(),
    }
    request.update(overrides)
    return request


def test_search_returns_top_k_with_fields(monkeypatch):
    monkeypatch.setattr(worker, "OpenVinoQueryEmbedder", _FakeEmbedder)

    response = worker.search(_request())

    assert response["ok"] is True
    assert [item["chunk_id"] for item in response["results"]] == ["c1", "c3"]
    assert response["results"][0]["covered_files"] == ["documents/a/1.md"]
    assert response["results"][0]["token_range"] == [0, 1]
    assert response["results"][0]["score"] > response["results"][1]["score"]


def test_search_rejects_bad_vectors(monkeypatch):
    monkeypatch.setattr(worker, "OpenVinoQueryEmbedder", _FakeEmbedder)

    response = worker.search(_request(vectors_b64=base64.b64encode(b"x").decode()))

    assert response["ok"] is False
    assert "vectors" in response["errors"][0]["message"]


def test_search_rejects_empty_query(monkeypatch):
    monkeypatch.setattr(worker, "OpenVinoQueryEmbedder", _FakeEmbedder)

    response = worker.search(_request(query="   "))

    assert response["ok"] is False


def test_worker_subprocess_entry_with_real_model():
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("embedding model is not cached locally")

    vectors = np.eye(384, dtype=np.float32)[:3]
    request = {
        "query": "付款期限",
        "top_k": 3,
        "model_id": DEFAULT_EMBEDDING_MODEL,
        "dimension": 384,
        "chunks": [_chunk(1), _chunk(2), _chunk(3)],
        "vectors_b64": base64.b64encode(vectors.tobytes()).decode(),
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
