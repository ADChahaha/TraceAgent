"""search_embedding 子进程路径：取消 kill、失败映射、真实 worker 端到端。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("openvino")

from service.file_extraction_agent.core.tools import embedding
from service.file_extraction_agent.core.tools.embedding import (
    Chunk,
    EmbeddingIndex,
    _search_embedding,
)


class _FakeEmbedding:
    def __init__(self):
        self._slot = asyncio.Semaphore(1)

    def search_slot(self):
        return self._slot


def _state() -> SimpleNamespace:
    return SimpleNamespace(document=None, embedding=_FakeEmbedding())


def _index(dimension: int = 2, model_id: str = "m") -> EmbeddingIndex:
    chunks = [
        Chunk(
            document="d",
            chunk_id=f"c{index}",
            text=f"t{index}",
            token_range=(0, 1),
            char_range=(0, 1),
            covered_files=[f"documents/a/{index}.md"],
        )
        for index in range(3)
    ]
    vectors = np.eye(dimension, dtype=np.float32)[: len(chunks)]
    return EmbeddingIndex(model_id=model_id, chunks=chunks, vectors=vectors, dimension=dimension)


async def test_search_cancellation_kills_worker(tmp_path, monkeypatch):
    pid_file = tmp_path / "pid.txt"
    script = tmp_path / "slow_worker.py"
    script.write_text(
        "import os, sys, time\n"
        "sys.stdin.buffer.read()\n"
        "open(os.environ['WORKER_PID_FILE'], 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKER_PID_FILE", str(pid_file))
    monkeypatch.setattr(embedding, "_worker_command", lambda: [sys.executable, str(script)])
    monkeypatch.setattr(embedding, "_get_index", lambda state: _index())

    task = asyncio.create_task(_search_embedding(_state(), query="x"))
    for _ in range(250):
        if pid_file.exists():
            break
        await asyncio.sleep(0.02)
    assert pid_file.exists(), "worker did not start"
    pid = int(pid_file.read_text())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    import psutil

    for _ in range(100):
        if not psutil.pid_exists(pid):
            break
        await asyncio.sleep(0.02)
    assert not psutil.pid_exists(pid), "worker process was not killed"


async def test_search_worker_failure_returns_error(tmp_path, monkeypatch):
    script = tmp_path / "fail_worker.py"
    script.write_text(
        "import sys\nsys.stdin.buffer.read()\nsys.stderr.write('boom')\nsys.exit(3)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(embedding, "_worker_command", lambda: [sys.executable, str(script)])
    monkeypatch.setattr(embedding, "_get_index", lambda state: _index())

    result = await _search_embedding(_state(), query="x")

    assert result["ok"] is False
    assert "boom" in result["errors"][0]["message"]


async def test_search_with_real_worker_returns_results(monkeypatch):
    from huggingface_hub import snapshot_download

    from service.document_resources.model import DEFAULT_EMBEDDING_MODEL

    try:
        snapshot_download(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("embedding model is not cached locally")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(
        embedding,
        "_get_index",
        lambda state: _index(dimension=384, model_id=DEFAULT_EMBEDDING_MODEL),
    )

    result = await _search_embedding(_state(), query="付款期限", top_k=2)

    assert result["ok"] is True
    assert len(result["results"]) == 2
    assert all(item["chunk_id"] for item in result["results"])
