"""纯 OpenVINO 查询编码器：与参考向量对齐，且不依赖 torch。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openvino")
pytest.importorskip("huggingface_hub")

from service.document_resources.model import DEFAULT_EMBEDDING_MODEL
from service.file_extraction_agent.core.tools.ov_embedder import OpenVinoQueryEmbedder

AGENT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bekko_query_vectors.json"


@pytest.fixture(autouse=True)
def _offline_hub(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


def _model_dir_or_skip() -> str:
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pytest.skip("embedding model is not cached locally")


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_encode_shape_and_unit_norm():
    _model_dir_or_skip()
    embedder = OpenVinoQueryEmbedder(DEFAULT_EMBEDDING_MODEL)

    vectors = embedder.encode(["付款期限是多少？", "合同如何提前终止？"])

    assert vectors.shape == (2, 384)
    assert vectors.dtype == np.float32
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_encode_matches_sentence_transformers_reference_vectors():
    model_dir = _model_dir_or_skip()
    fixture = _load_fixture()
    if Path(model_dir).name != fixture["revision"]:
        pytest.skip("local model revision differs from the recorded reference vectors")
    embedder = OpenVinoQueryEmbedder(DEFAULT_EMBEDDING_MODEL)

    mine = embedder.encode(fixture["texts"])
    theirs = np.asarray(fixture["vectors"], dtype=np.float32)

    cosine = (mine * theirs).sum(axis=1)
    assert np.all(cosine > 0.999), cosine


def test_ov_embedder_path_does_not_import_torch():
    _model_dir_or_skip()
    code = (
        "import sys\n"
        "from service.file_extraction_agent.core.tools.ov_embedder import OpenVinoQueryEmbedder\n"
        f"OpenVinoQueryEmbedder({DEFAULT_EMBEDDING_MODEL!r}).encode(['付款期限'])\n"
        "assert 'torch' not in sys.modules, 'torch was imported'\n"
        "assert 'sentence_transformers' not in sys.modules\n"
    )
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
