"""worker_client 子进程路径：取消/超时 kill、失败映射、真实 worker 端到端。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

from service.file_extraction_agent.core.tools import worker_client
from service.file_extraction_agent.core.tools.embedding import Chunk, EmbeddingIndex, index_to_payload


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


def _write_slow_worker(tmp_path: Path) -> tuple[Path, Path]:
    pid_file = tmp_path / "pid.txt"
    script = tmp_path / "slow_worker.py"
    script.write_text(
        "import os, sys, time\n"
        "sys.stdin.buffer.read()\n"
        "open(os.environ['WORKER_PID_FILE'], 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    return script, pid_file


async def _wait_for_file(path: Path) -> int:
    for _ in range(250):
        if path.exists():
            return int(path.read_text())
        await asyncio.sleep(0.02)
    raise AssertionError(f"{path} was not created")


async def test_run_operation_cancellation_kills_worker(tmp_path, monkeypatch):
    script, pid_file = _write_slow_worker(tmp_path)
    monkeypatch.setenv("WORKER_PID_FILE", str(pid_file))
    monkeypatch.setattr(worker_client, "_worker_command", lambda: [sys.executable, str(script)])

    task = asyncio.create_task(
        worker_client.run_operation(operation="read", args={"path": "a.md"}, workspace={"bucket": "b"})
    )
    pid = await _wait_for_file(pid_file)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    import psutil

    for _ in range(100):
        if not psutil.pid_exists(pid):
            break
        await asyncio.sleep(0.02)
    assert not psutil.pid_exists(pid), "worker process was not killed"


async def test_prepare_workspace_cancellation_kills_worker(tmp_path, monkeypatch):
    script, pid_file = _write_slow_worker(tmp_path)
    monkeypatch.setenv("WORKER_PID_FILE", str(pid_file))
    monkeypatch.setattr(worker_client, "_worker_command", lambda: [sys.executable, str(script)])

    task = asyncio.create_task(
        worker_client.prepare_workspace([{"type": "documents", "location": "s3://b/documents"}])
    )
    pid = await _wait_for_file(pid_file)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    import psutil

    for _ in range(100):
        if not psutil.pid_exists(pid):
            break
        await asyncio.sleep(0.02)
    assert not psutil.pid_exists(pid), "prepare worker was not killed"


async def test_run_operation_failure_returns_error(tmp_path, monkeypatch):
    script = tmp_path / "fail_worker.py"
    script.write_text(
        "import sys\nsys.stdin.buffer.read()\nsys.stderr.write('boom')\nsys.exit(3)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(worker_client, "_worker_command", lambda: [sys.executable, str(script)])

    result = await worker_client.run_operation(operation="read", args={}, workspace={"bucket": "b"})

    assert result["ok"] is False
    assert "boom" in result["errors"][0]["message"]


async def test_prepare_workspace_maps_invalid_resource_to_value_error(tmp_path, monkeypatch):
    script = tmp_path / "invalid_worker.py"
    script.write_text(
        "import json, sys\nsys.stdin.buffer.read()\n"
        "sys.stdout.write(json.dumps({'ok': False, 'kind': 'invalid', 'message': 'bad refs'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(worker_client, "_worker_command", lambda: [sys.executable, str(script)])

    with pytest.raises(ValueError, match="bad refs"):
        await worker_client.prepare_workspace([{"type": "documents", "location": "s3://b/documents"}])


async def test_prepare_workspace_empty_refs_rejects_without_worker():
    with pytest.raises(ValueError, match="resource_path"):
        await worker_client.prepare_workspace([])


async def test_real_worker_search_returns_results(monkeypatch):
    pytest.importorskip("openvino")
    from huggingface_hub import snapshot_download

    from service.document_resources.model import DEFAULT_EMBEDDING_MODEL

    try:
        snapshot_download(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("embedding model is not cached locally")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    workspace = {"index": index_to_payload(_index(dimension=384, model_id=DEFAULT_EMBEDDING_MODEL))}
    result = await worker_client.run_operation(
        operation="search_embedding",
        args={"query": "付款期限", "top_k": 2},
        workspace=workspace,
    )

    assert result["ok"] is True
    assert len(result["results"]) == 2
    assert all(item["chunk_id"] for item in result["results"])
