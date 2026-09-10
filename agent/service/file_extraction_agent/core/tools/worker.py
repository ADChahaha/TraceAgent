"""语义检索子进程：读一个 JSON 请求 → 加载 OpenVINO 查询编码器 → 返回 top-k。

实现步骤：

```text
stdin（整个 JSON）
  -> query / top_k / model_id / dimension / chunks / vectors_b64
  -> 校验向量长度与 dimension 一致
  -> OpenVinoQueryEmbedder(model_id).encode([query]) 并归一化
  -> scores = vectors @ query，取 top_k
  -> 返回 {ok, query, results:[{score, document, chunk_id, text, token_range, covered_files}]}

任何异常都转成 {"ok": false, "errors": [{"message": ...}]}，进程退出码仍为 0，
由父进程按响应内容判断；父进程只负责取消时 kill 本进程。
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

import numpy as np

from service.file_extraction_agent.core.tools.ov_embedder import OpenVinoQueryEmbedder

MAX_TOP_K = 50


def search(request: dict[str, Any]) -> dict[str, Any]:
    query = request.get("query")
    if not isinstance(query, str) or not query.strip():
        return _error("query is required")
    chunks = request.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return _error("chunks must be a non-empty list")
    dimension = int(request.get("dimension") or 0)
    top_k = max(1, min(int(request.get("top_k") or 5), min(MAX_TOP_K, len(chunks))))

    vectors = _decode_vectors(request.get("vectors_b64"), len(chunks), dimension)
    if vectors is None:
        return _error("invalid index vectors")

    embedder = OpenVinoQueryEmbedder(str(request.get("model_id") or ""))
    query_vector = np.asarray(embedder.encode([query]), dtype=np.float32).reshape(-1)
    if query_vector.shape[0] != vectors.shape[1]:
        return _error("query dimension does not match index vectors")
    norm = float(np.linalg.norm(query_vector))
    if norm <= 0:
        return _error("query vector is empty")
    query_vector = query_vector / norm

    scores = vectors @ query_vector
    order = np.argsort(-scores)[:top_k]
    results = []
    for position in order:
        chunk = chunks[int(position)]
        results.append(
            {
                "score": float(scores[int(position)]),
                "document": chunk.get("document", ""),
                "chunk_id": chunk.get("chunk_id", ""),
                "text": chunk.get("text", ""),
                "token_range": list(chunk.get("token_range") or (0, 0)),
                "covered_files": list(chunk.get("covered_files") or []),
            }
        )
    return {"ok": True, "query": query, "results": results}


def _decode_vectors(encoded: Any, count: int, dimension: int) -> np.ndarray | None:
    if not isinstance(encoded, str) or dimension <= 0 or count <= 0:
        return None
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return None
    expected = count * dimension * 4
    if len(raw) != expected:
        return None
    vectors = np.frombuffer(raw, dtype="<f4").reshape(count, dimension).astype(np.float32)
    if not np.isfinite(vectors).all():
        return None
    return vectors


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "errors": [{"message": message}]}


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = search(request)
    except Exception as exc:  # noqa: BLE001 - 子进程边界统一转错误响应
        response = _error(str(exc))
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
