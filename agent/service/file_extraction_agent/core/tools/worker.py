"""统一工具子进程入口：stdin JSON 请求 → operation 分发 → stdout JSON 响应。

实现步骤：

```text
stdin（整个 JSON）
  -> {"operation": ..., "args": {...}, "workspace": {...}?}
  -> prepare：按 resource_path 拉取归档、校验索引 → {ok, workspace}
  -> ls / grep / read：从 workspace payload 重建文档树 → 执行同步工具逻辑
  -> search_embedding：从 workspace.index 解码 chunks/vectors → OpenVINO 编码 query → top-k
  -> 任何异常都转 {"ok": false, "errors": [{"message": ...}]}，进程退出码仍为 0

父进程只负责取消/超时/正常结束时 kill 本进程。
"""

from __future__ import annotations

import base64
import json
import sys
from types import SimpleNamespace
from typing import Any

import numpy as np

from service.file_extraction_agent.core.tools.grep import _grep
from service.file_extraction_agent.core.tools.ls import _ls
from service.file_extraction_agent.core.tools.read import _read
from service.file_extraction_agent.core.tools.workspace import (
    ToolWorkspace,
    document_tree_from_payload,
    load_workspace_payload,
)

MAX_TOP_K = 50


def handle(request: dict[str, Any]) -> dict[str, Any]:
    """分发一个请求；工具 op 返回工具结果，prepare 返回 workspace payload。"""
    operation = request.get("operation")
    args = request.get("args")
    args = args if isinstance(args, dict) else {}
    try:
        if operation not in {"prepare", "ls", "grep", "read", "search_embedding"}:
            return _error(f"unknown operation: {operation}")
        if operation == "prepare":
            return _prepare(args.get("resource_path"))
        workspace = request.get("workspace")
        if not isinstance(workspace, dict):
            return _error("workspace payload is required")
        if operation == "ls":
            return _ls(_read_only_workspace(workspace), str(args.get("path") or ""))
        if operation == "grep":
            return _grep(
                _read_only_workspace(workspace),
                query=str(args.get("query") or ""),
                scope=str(args.get("scope") or ""),
                max_results=int(args.get("max_results") or 20),
            )
        if operation == "read":
            return _read(_read_only_workspace(workspace), str(args.get("path") or ""))
        if operation == "search_embedding":
            return search(
                workspace.get("index") if isinstance(workspace.get("index"), dict) else {},
                query=args.get("query"),
                top_k=args.get("top_k"),
            )
        return _error(f"unknown operation: {operation}")
    except Exception as exc:  # noqa: BLE001 - 子进程边界统一转错误响应
        return _error(str(exc))


def _prepare(resource_path: Any) -> dict[str, Any]:
    if not isinstance(resource_path, list):
        return {"ok": False, "kind": "invalid", "message": "resource_path is required"}
    refs = [
        SimpleNamespace(type=item.get("type"), location=item.get("location"))
        for item in resource_path
        if isinstance(item, dict)
    ]
    if not refs:
        return {"ok": False, "kind": "invalid", "message": "resource_path is required"}
    try:
        payload = load_workspace_payload(refs)
    except ValueError as exc:
        return {"ok": False, "kind": "invalid", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - prepare 边界统一转内部错误
        return {"ok": False, "kind": "internal", "message": str(exc)}
    return {"ok": True, "workspace": payload}


def _read_only_workspace(workspace: dict[str, Any]) -> ToolWorkspace:
    return ToolWorkspace(document=document_tree_from_payload(workspace))


def _embedder_class():
    from service.file_extraction_agent.core.tools.ov_embedder import OpenVinoQueryEmbedder

    return OpenVinoQueryEmbedder


def search(index: dict[str, Any], *, query: Any, top_k: Any = 5) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        return _error("query is required")
    chunks = index.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return _error("chunks must be a non-empty list")
    dimension = int(index.get("dimension") or 0)
    top_k = max(1, min(int(top_k or 5), min(MAX_TOP_K, len(chunks))))

    vectors = _decode_vectors(index.get("vectors_b64"), len(chunks), dimension)
    if vectors is None:
        return _error("invalid index vectors")

    embedder = _embedder_class()(str(index.get("model_id") or ""))
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
        response = handle(request)
    except Exception as exc:  # noqa: BLE001 - 子进程边界统一转错误响应
        response = _error(str(exc))
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
