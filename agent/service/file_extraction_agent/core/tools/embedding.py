"""语义检索：资源路径 → 加载已有索引 → 子进程编码 query → top-k 候选。

实现步骤：

```text
state.embedding.load_index()
  -> 读取 manifest.json / index.json / vectors.npy，校验维度与 covered_files
  -> 返回内存 EmbeddingIndex（chunks + vectors）

_search_embedding(state, query, top_k)
  -> 空 query 直接返回 BAD_QUERY
  -> load_index（阻塞读经 asyncio.to_thread）
  -> 组装 worker 请求：query/top_k/model_id/dimension/chunks/vectors_b64
  -> 每轮 completion 一个信号量，串行启动 worker 子进程
  -> worker.py 在子进程里用纯 OpenVINO 编码 query 并返回 top-k
  -> 取消时在 finally kill 子进程，保证可固定时间中断
```

索引加载后缓存；查询模型不在本进程加载，避免 torch/transformers 启动成本。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from botocore.exceptions import ClientError
from langchain_core.tools import BaseTool, tool
from service.file_extraction_agent.core.contracts import JsonObject, JsonValue
from service.object_store import ObjectStore

if TYPE_CHECKING:
    from service.file_extraction_agent.core.tools.workspace import ToolWorkspace

AGENT_ROOT = Path(__file__).resolve().parents[4]
WORKER_MODULE = "service.file_extraction_agent.core.tools.worker"
WORKER_TIMEOUT_SECONDS = 120.0


@dataclass
class Chunk:
    """检索命中单元：一个固定 token 窗口切出的文本片段。"""

    document: str
    chunk_id: str
    text: str
    token_range: tuple[int, int] = (0, 0)
    char_range: tuple[int, int] = (0, 0)
    covered_files: list[str] = field(default_factory=list)


@dataclass
class EmbeddingIndex:
    """一个文档集的向量索引。"""

    model_id: str
    chunks: list[Chunk]
    vectors: NDArray[np.float32]
    dimension: int = 0


def _resolve_document_key(document_root: str, relative: str) -> str | None:
    """把索引引用的相对 .md 路径解析为桶内对象 key；越界返回 None。"""
    if not relative or relative.startswith("/") or ".." in relative.split("/"):
        return None
    return f"{document_root}/{relative}"


class EmbeddingResources:
    """资源桶 → 校验并缓存清单/索引；为每轮 completion 提供查询串行信号量。"""

    def __init__(self, store: ObjectStore, bucket: str, root_key: str = "index") -> None:
        self.store = store
        self.bucket = bucket
        self.root_key = root_key.rstrip("/")
        self.model_id: str | None = None
        self.backend: str | None = None
        self._index: EmbeddingIndex | None = None
        self._lock = threading.RLock()
        self._search_semaphore: asyncio.Semaphore | None = None

    def _get(self, key: str) -> bytes:
        data = self.store.get_object(self.bucket, key)
        if data is None:
            raise ValueError(f"missing object: {key}")
        return data

    def _read_text(self, key: str) -> str:
        return self._get(key).decode("utf-8")

    def load_index(self) -> EmbeddingIndex:
        """读取清单和 numpy 索引 → 校验版本、维度及引用 → 缓存只读索引；失败抛 ValueError。"""
        with self._lock:
            if self._index is None:
                try:
                    self._index = self._read_index()
                except (OSError, ValueError, KeyError, TypeError, ClientError) as exc:
                    raise ValueError(f"invalid document resource: {exc}") from exc
            return self._index

    def _read_index(self) -> EmbeddingIndex:
        manifest = json.loads(self._read_text("manifest.json"))
        if manifest["version"] != 1:
            raise ValueError("unsupported resource version")
        model_id, backend = manifest["embedding_model"], manifest["embedding_backend"]
        if not isinstance(model_id, str) or not model_id or backend not in {"openvino", "torch"}:
            raise ValueError("invalid embedding configuration")
        meta = json.loads(self._read_text(f"{self.root_key}/index.json"))
        if meta["model_id"] != model_id:
            raise ValueError("index model does not match manifest")
        vectors = np.load(BytesIO(self._get(f"{self.root_key}/vectors.npy")), allow_pickle=False)
        chunks = [Chunk(**item) for item in meta["chunks"]]
        if (
            vectors.ndim != 2
            or vectors.shape != (len(chunks), meta["dimension"])
            or not np.isfinite(vectors).all()
        ):
            raise ValueError("invalid index vectors")
        document_root = "documents"
        resolved_chunks = []
        for chunk in chunks:
            if not chunk.covered_files:
                raise ValueError("chunk requires document references")
            files = []
            for relative in chunk.covered_files:
                key = _resolve_document_key(document_root, relative)
                if key is None or self.store.get_object(self.bucket, key) is None:
                    raise ValueError("invalid index document reference")
                files.append(key)
            resolved_chunks.append(replace(chunk, covered_files=files))
        self.model_id, self.backend = model_id, backend
        return EmbeddingIndex(model_id, resolved_chunks, vectors, meta["dimension"])

    def search_slot(self) -> asyncio.Semaphore:
        """每轮 completion 内串行启动 worker，避免并发进程导致的内存尖峰。"""
        if self._search_semaphore is None:
            self._search_semaphore = asyncio.Semaphore(1)
        return self._search_semaphore


def search_top_k(
    query_vec: NDArray[np.float32], index: EmbeddingIndex, top_k: int = 5
) -> list[JsonValue]:
    """余弦检索，返回按分数降序的候选 chunk 列表。"""

    if index.vectors.size == 0 or index.vectors.ndim != 2:
        return []
    query = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    _normalize(query)
    if index.vectors.shape[1] != query.shape[0]:
        raise ValueError("query dimension does not match index vectors")
    scores = index.vectors @ query
    order = np.argsort(-scores)[: max(0, top_k)]
    results: list[JsonValue] = []
    for position in order:
        score = float(scores[position])
        chunk = index.chunks[int(position)]
        results.append(
            {
                "score": score,
                "document": chunk.document,
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "token_range": list(chunk.token_range),
                "covered_files": list(chunk.covered_files),
            }
        )
    return results


def _normalize(matrix: NDArray[np.float32]) -> None:
    if matrix.ndim == 1:
        norm = np.linalg.norm(matrix)
        if norm > 0:
            matrix /= norm
        return
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    matrix /= norms


def _get_index(state: "ToolWorkspace") -> EmbeddingIndex:
    """加载或复用工具上下文中的已有索引，问答期间不构建文档向量。"""
    return state.embedding.load_index()


def _worker_command() -> list[str]:
    return [sys.executable, "-m", WORKER_MODULE]


def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def _run_worker(request: dict[str, Any]) -> dict[str, Any]:
    """启动 worker 子进程，发送请求并读取响应；取消/超时都会 kill 进程。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(AGENT_ROOT), env.get("PYTHONPATH", "")) if part
    )
    process = await asyncio.create_subprocess_exec(
        *_worker_command(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(AGENT_ROOT),
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8")),
            timeout=WORKER_TIMEOUT_SECONDS,
        )
        if process.returncode != 0 and not stdout:
            return _error(f"embedding worker failed: {stderr.decode('utf-8', 'replace')[:500]}")
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _error(f"invalid embedding worker response: {exc}")
        if not isinstance(response, dict):
            return _error("invalid embedding worker response")
        return response
    except asyncio.TimeoutError:
        return _error("embedding worker timed out")
    finally:
        _kill(process)


def _build_worker_request(index: EmbeddingIndex, query: str, top_k: int) -> dict[str, Any]:
    vectors = np.ascontiguousarray(index.vectors, dtype="<f4")
    dimension = int(index.dimension or (vectors.shape[1] if vectors.ndim == 2 else 0))
    return {
        "query": query,
        "top_k": top_k,
        "model_id": index.model_id,
        "dimension": dimension,
        "chunks": [asdict(chunk) for chunk in index.chunks],
        "vectors_b64": base64.b64encode(vectors.tobytes()).decode("ascii"),
    }


async def _search_embedding(
    state: "ToolWorkspace",
    *,
    query: str,
    top_k: int = 5,
) -> JsonObject:
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "errors": [{"code": "BAD_QUERY", "message": "query is required"}]}
    top_k_bounded = max(1, min(int(top_k or 5), 20))
    index = await asyncio.to_thread(_get_index, state)
    request = _build_worker_request(index, query, top_k_bounded)
    async with state.embedding.search_slot():
        return await _run_worker(request)


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "errors": [{"message": message}]}


def build_search_embedding(state: "ToolWorkspace") -> BaseTool:
    @tool
    async def search_embedding(query: str, top_k: int = 5) -> JsonObject:
        """Semantic search across chunks using embeddings.

        Returns up to top_k text chunks that are semantically (not just
        lexically) related to query. Use when grep returns nothing useful or
        when the answer's wording differs from the document's wording.
        Chunks are fixed windows that may span multiple .md block files — each
        result carries a `document` (source doc name) and `covered_files` (the
        .md block paths the chunk spans), so you can read them to verify and
        cite. Each result also includes the chunk `text` directly.
        Results are candidates only, NOT final evidence. Always read a covered
        file before citing it in your answer.
        """

        return await _search_embedding(state, query=query, top_k=top_k)

    return search_embedding


__all__ = [
    "build_search_embedding",
    "_search_embedding",
    "_get_index",
    "_build_worker_request",
    "_run_worker",
    "_worker_command",
]
