"""用轻量 embedding 准备真实资源，返回资源定位数组，供问答运行时测试复用。"""

import uuid

import numpy as np
import pytest

from document_service.document_resources import model, publish_resources
from document_service.document_resources.schemas import InputDocument
from traceagent_shared.object_store import build_s3_object_store


@pytest.fixture
def resource_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path / "resources"))

    class Embedder:
        def tokenize(self, text):
            return [(i, i + 1) for i in range(len(text))]

        def encode(self, texts):
            return np.ones((len(texts), 3), dtype=np.float32)

    monkeypatch.setattr(model, "get_embedder", lambda **kwargs: Embedder())
    bucket = f"res_{uuid.uuid4().hex[:8]}"
    return publish_resources(build_s3_object_store(), bucket,
                             [InputDocument(filename="contract.html", html="<h1>合同</h1><p>Either party may terminate.</p>")])
