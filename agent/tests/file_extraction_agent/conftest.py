"""用轻量 embedding 准备真实资源，返回资源定位数组，供问答运行时测试复用。"""

import numpy as np
import pytest

from service.document_resources import model, prepare_resources
from service.document_resources.schemas import InputDocument


@pytest.fixture
def resource_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))

    class Embedder:
        def tokenize(self, text):
            return [(i, i + 1) for i in range(len(text))]

        def encode(self, texts):
            return np.ones((len(texts), 3), dtype=np.float32)

    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: Embedder())
    return prepare_resources([InputDocument(filename="contract.html", html="<h1>合同</h1><p>Either party may terminate.</p>")])
