from pathlib import Path

import numpy as np

from service.file_extraction_agent.core.tools.embedding import index as cache
from service.file_extraction_agent.core.tools.embedding import model
from service.file_extraction_agent.manager import prepare_completion_state
from service.file_extraction_agent.schemas import DocumentQaMessage, InputDocument


def test_task_cache_reuses_vectors_and_rebases_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "EMBEDDING_INDEX_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(model, "get_tokenizer", lambda _: lambda text: [(i, i + 1) for i in range(len(text))])

    class Embedder:
        calls = 0

        def encode(self, texts):
            self.calls += 1
            return np.ones((len(texts), 3))

    embedder = Embedder()

    def load(completion_id, task_id, html="<p>same content</p>"):
        state = prepare_completion_state(
            completion_id=completion_id, task_id=task_id, workspace_root=tmp_path / "work",
            documents=[InputDocument(filename="a.html", html=html)],
            messages=[DocumentQaMessage(role="user", content="问题")],
        )
        state.embedding_model = "fake"
        return state, cache._get_index(state, embedder)

    first_state, first = load("cmp1", "task1")
    second_state, second = load("cmp2", "task1")
    assert embedder.calls == 1
    assert first.chunks[0].text == second.chunks[0].text
    for path in second.chunks[0].covered_files:
        assert Path(path).is_relative_to(second_state.document.root)
        assert Path(path).is_file()
        assert not Path(path).is_relative_to(first_state.document.root)
    load("cmp3", "task2")
    assert embedder.calls == 2
    load("cmp4", "task1", "<p>changed content</p>")
    assert embedder.calls == 3
