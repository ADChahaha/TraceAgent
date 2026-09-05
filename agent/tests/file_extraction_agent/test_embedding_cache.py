"""资源索引跨轮复用，查询使用资源记录的模型配置。"""

from pathlib import Path
import numpy as np

from service.document_resources import model
from service.file_extraction_agent.core.tools.embedding import _search_embedding
from service.file_extraction_agent.core.tools import embedding


def test_resource_reuses_vectors_and_preserves_paths(resource_path, monkeypatch):
    def fail(**kwargs):
        raise AssertionError("加载资源不能调用 embedding")
    monkeypatch.setattr(model, "get_embedder", fail)
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    contexts = [open_workspace(resource_path) for _ in range(2)]
    indexes = [context.embedding.load_index() for context in contexts]
    assert np.array_equal(indexes[0].vectors, indexes[1].vectors)
    assert contexts[0].document.root == contexts[1].document.root
    assert contexts[0].embedding.load_index() is indexes[0]
    for index in indexes:
        for chunk in index.chunks:
            assert all(Path(path).is_file() for path in chunk.covered_files)


def test_query_uses_recorded_model_after_env_change(resource_path, monkeypatch):
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    context = open_workspace(resource_path)
    monkeypatch.setenv("EMBEDDING_MODEL", "other-model")
    monkeypatch.setenv("EMBEDDING_BACKEND", "other-backend")
    calls = []
    texts_seen = []
    class Embedder:
        def encode(self, texts):
            texts_seen.extend(texts)
            return np.ones((len(texts), 3), dtype=np.float32)
    def get_embedder(**kwargs):
        calls.append(kwargs)
        return Embedder()
    monkeypatch.setattr(embedding, "get_embedder", get_embedder)
    result = _search_embedding(context, query="notice")
    assert result["ok"] is True
    assert calls == [{"model_id": context.embedding.model_id, "backend": context.embedding.backend}]
    assert texts_seen == ["notice"]


def test_parallel_queries_share_tool_model_and_index(resource_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from service.file_extraction_agent.core.tools.workspace import open_workspace
    context = open_workspace(resource_path)
    calls, loads = [], []
    original_load = embedding.np.load

    class Embedder:
        def encode(self, texts):
            return np.ones((len(texts), 3), dtype=np.float32)

    def get_embedder(**kwargs):
        calls.append(kwargs)
        return Embedder()

    def load(*args, **kwargs):
        loads.append(args[0])
        return original_load(*args, **kwargs)

    monkeypatch.setattr(embedding, "get_embedder", get_embedder)
    monkeypatch.setattr(embedding.np, "load", load)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _search_embedding(context, query="notice"), range(4)))
    assert all(result["ok"] for result in results)
    assert len(calls) == len(loads) == 1
