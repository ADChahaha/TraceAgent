"""prepare 子进程产物：归档 bytes + 已解析索引组成的 workspace payload。"""

from __future__ import annotations

import base64
import io
import zipfile

import numpy as np

from service.file_extraction_agent.core.tools.embedding import Chunk, EmbeddingIndex, index_to_payload
from service.file_extraction_agent.core.tools.workspace import (
    document_tree_from_payload,
    load_workspace_payload,
)


def test_prepare_payload_contains_archive_and_resolved_index(resource_path):
    payload = load_workspace_payload(resource_path)

    assert payload["bucket"]
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["documents_archive_b64"])))
    assert archive.namelist()
    index = payload["index"]
    assert index["model_id"]
    assert index["dimension"] > 0
    assert index["chunks"]
    assert all(
        path.startswith("documents/")
        for chunk in index["chunks"]
        for path in chunk["covered_files"]
    )


def test_document_tree_from_payload_reads_without_storage(resource_path):
    payload = load_workspace_payload(resource_path)
    tree = document_tree_from_payload(payload)

    keys = _first_md_keys(tree)
    assert keys
    assert "terminate" in tree.read(keys[0])


def test_index_to_payload_preserves_vectors():
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    index = EmbeddingIndex(
        "m",
        [Chunk(document="d", chunk_id="c1", text="t1"), Chunk(document="d", chunk_id="c2", text="t2")],
        vectors,
        2,
    )

    payload = index_to_payload(index)

    assert payload["model_id"] == "m"
    assert payload["dimension"] == 2
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["c1", "c2"]
    raw = np.frombuffer(base64.b64decode(payload["vectors_b64"]), dtype="<f4")
    assert np.array_equal(raw, vectors.reshape(-1))


def _first_md_keys(tree) -> list[str]:
    keys: list[str] = []

    def collect(prefix: str) -> None:
        for entry in tree.entries(prefix):
            if entry.kind == "dir":
                collect(entry.path)
            elif entry.kind == "md":
                keys.append(entry.path)

    collect("")
    return keys
