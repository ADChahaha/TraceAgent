"""资源索引跨轮复用，查询使用资源记录的模型配置。"""

from pathlib import Path
import numpy as np

from service.document_resources import model
from service.file_extraction_agent.core.graph import build_graph_state
from service.file_extraction_agent.core.tools.embedding import _search_embedding
from service.file_extraction_agent.schemas import DocumentQaMessage


def test_resource_reuses_vectors_and_preserves_paths(resource_path, monkeypatch):
    def fail(**kwargs):
        raise AssertionError("加载资源不能调用 embedding")
    monkeypatch.setattr(model, "get_embedder", fail)
    states = [build_graph_state(resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")]) for _ in range(2)]
    assert np.array_equal(states[0].index.vectors, states[1].index.vectors)
    assert states[0].document.root == states[1].document.root
    for state in states:
        assert not hasattr(state, "task_id")
        assert not hasattr(state, "completion_id")
        for chunk in state.index.chunks:
            assert all(Path(path).is_file() for path in chunk.covered_files)


def test_query_uses_recorded_model_after_env_change(resource_path, monkeypatch):
    state = build_graph_state(resource_path=resource_path, messages=[DocumentQaMessage(role="user", content="问题")])
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
    monkeypatch.setattr(model, "get_embedder", get_embedder)
    result = _search_embedding(state, query="notice")
    assert result["ok"] is True
    assert calls == [{"model_id": state.embedding_model, "backend": state.embedding_backend}]
    assert texts_seen == ["notice"]
