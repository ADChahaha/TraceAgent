"""资源索引跨轮复用，查询请求使用资源记录的模型配置，worker 串行启动。"""

import asyncio
from pathlib import Path

import numpy as np

from service.document_resources import model
from service.file_extraction_agent.core.tools import embedding
from service.file_extraction_agent.core.tools.embedding import _search_embedding


def test_resource_reuses_vectors_and_preserves_paths(resource_path, monkeypatch):
    def fail(**kwargs):
        raise AssertionError("加载资源不能调用 embedding")
    monkeypatch.setattr(model, "get_embedder", fail)
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    contexts = [open_workspace(resource_path) for _ in range(2)]
    indexes = [context.embedding.load_index() for context in contexts]
    assert np.array_equal(indexes[0].vectors, indexes[1].vectors)
    assert contexts[0].document.root_key == contexts[1].document.root_key
    assert contexts[0].document.bucket == contexts[1].document.bucket
    assert contexts[0].embedding.load_index() is indexes[0]
    for index in indexes:
        for chunk in index.chunks:
            assert all(path.startswith("documents/") for path in chunk.covered_files)


async def test_query_uses_recorded_model_after_env_change(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    context = open_workspace(resource_path)
    context.embedding.load_index()
    monkeypatch.setenv("EMBEDDING_MODEL", "other-model")
    monkeypatch.setenv("EMBEDDING_BACKEND", "other-backend")
    requests: list[dict] = []

    async def fake_worker(request):
        requests.append(request)
        return {"ok": True, "query": request["query"], "results": []}

    monkeypatch.setattr(embedding, "_run_worker", fake_worker)

    result = await _search_embedding(context, query="notice")

    assert result["ok"] is True
    assert requests[0]["model_id"] == context.embedding.model_id


async def test_parallel_queries_load_index_once_and_serialize_worker(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    context = open_workspace(resource_path)
    loads = []
    original_load = embedding.np.load
    active = {"now": 0, "max": 0}

    async def fake_worker(request):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return {"ok": True, "query": request["query"], "results": []}

    def load(*args, **kwargs):
        loads.append(args[0])
        return original_load(*args, **kwargs)

    monkeypatch.setattr(embedding, "_run_worker", fake_worker)
    monkeypatch.setattr(embedding.np, "load", load)

    results = await asyncio.gather(
        *(_search_embedding(context, query="notice") for _ in range(4))
    )

    assert all(result["ok"] for result in results)
    assert len(loads) == 1
    assert active["max"] == 1
