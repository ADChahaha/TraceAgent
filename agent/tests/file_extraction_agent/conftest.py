"""用轻量 embedding 准备真实资源路径，供问答运行时测试复用。"""

import numpy as np
import pytest

from service.document_resources import model, prepare_resources
from service.document_resources.schemas import InputDocument


@pytest.fixture
def resource_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))

    class Embedder:
        def encode(self, texts):
            return np.ones((len(texts), 3), dtype=np.float32)

    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: Embedder())
    monkeypatch.setattr(model, "get_tokenizer", lambda *a: lambda text: [(i, i + 1) for i in range(len(text))])
    return prepare_resources([InputDocument(filename="contract.html", html="<h1>合同</h1><p>Either party may terminate.</p>")])
