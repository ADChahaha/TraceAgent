"""Embedding index and cosine search for document-QA candidate recall.

`search.py` 提供纯 numpy 的向量检索层：把单个文档的文本流按固定 token 窗口
加 overlap 切成 chunk（chunk 可在文档内部跨越多个 `.md` 块），对每个 chunk
编码向量并建索引；查询时只对 query 编码一次，再用余弦相似度取 top-k。

本模块**不依赖任何真实 embedding 模型或向量库**：embedder 和 tokenize 都是
可注入的替身，便于单元测试。真实模型封装见 `model.py`，
索引持久化与构建编排见 `resources.py`。

实现步骤：

```text
streams: {document_name: [(md_path, text), ...]}
  -> 遍历每个文档，经 tokenize 把各 .md 块文本合成带字符 offsets 的 token 流
  -> tokenize 只是按字符连续的 token 序列，能同时给出每个 token 的字符区间
  -> 按 chunk_size + overlap 在 token 级滑窗切 chunk
  -> 每个 chunk 记录(document, chunk_id, text, token_range,
      covered_files=[该 chunk 覆盖到的 .md 路径])
  -> embedder.encode([chunk.text for chunk in chunks]) 得到 vectors
  -> 返回 EmbeddingIndex(chunks, vectors)

search_top_k(query_vec, index, top_k)
  -> 与每个 chunk 向量做点积（前提：已 L2 归一化）
  -> 按分数降序取 top_k，返回带 text/document/covered_files/chunk_id 的 dict 列表
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

# 字符级 tokenize 兜底：把文本按字符切成 (start, end) 区间。真实场景里由
# tools.py 用模型 tokenizer 替换，以保证 chunk 语义与 embedding 输入一致。
def _default_tokenizer(text: str) -> Sequence[tuple[int, int]]:
    return [(i, i + 1) for i in range(len(text))]


DEFAULT_TOKENIZER: Callable[[str], Sequence[tuple[int, int]]] = _default_tokenizer


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
    vectors: np.ndarray
    dimension: int = 0


@dataclass
class ChunkSpan:
    """chunk_text 返回的单个跨度。"""

    text: str
    token_range: tuple[int, int]
    char_range: tuple[int, int]


def chunk_text(
    text: str,
    *,
    tokenize: Callable[[str], Sequence[tuple[int, int]]] | None = None,
    chunk_size: int = 256,
    overlap: int = 32,
) -> list[ChunkSpan]:
    """把单段文本按 token 滑窗切 chunk。

    tokenize 返回带字符 offsets 的 token 序列（每项为 (start, end) 字符区间）。
    chunk 覆盖的 token 起点从 0 开始，每次前进 `chunk_size - overlap` 个 token；
    最后一个 chunk 即使不足 chunk_size 也保留。每个 chunk 同时记录它在原文本中
    的字符区间 char_range，供覆盖关系判断（token 与字符在多字节 tokenizer 下
    并不一一对应）。
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")
    tokenizer = tokenize or DEFAULT_TOKENIZER
    tokens = list(tokenizer(text))
    if not tokens:
        return [ChunkSpan(text="", token_range=(0, 0), char_range=(0, 0))]

    step = max(1, chunk_size - overlap)
    spans: list[ChunkSpan] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        char_start = chunk_tokens[0][0] if chunk_tokens else 0
        char_end = chunk_tokens[-1][1] if chunk_tokens else 0
        chunk_text_value = text[char_start:char_end] if chunk_tokens else ""
        spans.append(ChunkSpan(text=chunk_text_value, token_range=(start, end), char_range=(char_start, char_end)))
        if end >= len(tokens):
            break
        start += step
    return spans


def build_index(
    streams: dict[str, list[tuple[str, str]]],
    *,
    embedder: Any,
    model_id: str,
    tokenize: Callable[[str], Sequence[tuple[int, int]]] | None = None,
    chunk_size: int = 256,
    overlap: int = 32,
) -> EmbeddingIndex:
    """为一个文档集构建向量索引。

    streams: {document_name: [(md_path, text), ...]}，每个文档按文件树顺序给出
    其 `.md` 块。chunk 在文档内跨块切分，covered_files 记录该 chunk 覆盖的
    所有 `.md` 路径。
    """

    chunks: list[Chunk] = []
    for document_name, segments in streams.items():
        if not segments:
            continue
        text = "\n".join(text for _, text in segments)
        # 维护每个 .md 块在整条文本流中的字符区间，用于计算覆盖关系
        segment_boundaries: list[tuple[int, int, str]] = []
        cursor = 0
        for path, seg in segments:
            next_cursor = cursor + len(seg) + (1 if cursor else 0)
            segment_boundaries.append((cursor, next_cursor, path))
            cursor = next_cursor
        # 用 token 滑窗切 chunk，每个 chunk 记录它在整条文本流中的字符区间
        spans = chunk_text(text, tokenize=tokenize, chunk_size=chunk_size, overlap=overlap)
        for index, span in enumerate(spans):
            covered_files = _covered_files(span.char_range, segment_boundaries)
            chunks.append(
                Chunk(
                    document=document_name,
                    chunk_id=f"{document_name}#c{index + 1}",
                    text=span.text,
                    token_range=span.token_range,
                    char_range=span.char_range,
                    covered_files=covered_files,
                )
            )

    if not chunks:
        vectors = np.zeros((0, 0), dtype=np.float32)
        return EmbeddingIndex(model_id=model_id, chunks=[], vectors=vectors, dimension=0)

    vectors = np.asarray(embedder.encode([chunk.text for chunk in chunks]), dtype=np.float32)
    _normalize(vectors)
    dimension = int(vectors.shape[1]) if vectors.ndim == 2 else 0
    return EmbeddingIndex(model_id=model_id, chunks=chunks, vectors=vectors, dimension=dimension)


def search_top_k(query_vec: np.ndarray, index: EmbeddingIndex, top_k: int = 5) -> list[dict[str, Any]]:
    """余弦检索，返回按分数降序的候选 chunk 列表。"""

    if index.vectors.size == 0 or index.vectors.ndim != 2:
        return []
    query = np.asarray(query_vec, dtype=np.float32).reshape(-1)
    _normalize(query)
    if index.vectors.shape[1] != query.shape[0]:
        raise ValueError("query dimension does not match index vectors")
    scores = index.vectors @ query
    order = np.argsort(-scores)[: max(0, top_k)]
    results: list[dict[str, Any]] = []
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


def _covered_files(
    char_range: tuple[int, int],
    segment_boundaries: list[tuple[int, int, str]],
) -> list[str]:
    """返回与给定字符区间有交集的 .md 文件路径。

    segment_boundaries 每项为 (seg_start, seg_end, path)，seg_start/seg_end 是
    该 .md 块在整条文档文本流中的字符区间；char_range 是 chunk 的字符区间。
    只要二者相交，就认为该 chunk "覆盖" 了这个 .md 块。
    """

    char_start, char_end = char_range
    covered: list[str] = []
    for seg_start, seg_end, path in segment_boundaries:
        if seg_start < char_end and seg_end > char_start:
            covered.append(path)
    return covered


def _normalize(matrix: np.ndarray) -> None:
    if matrix.ndim == 1:
        norm = np.linalg.norm(matrix)
        if norm > 0:
            matrix /= norm
        return
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    matrix /= norms


__all__ = [
    "Chunk",
    "ChunkSpan",
    "EmbeddingIndex",
    "build_index",
    "chunk_text",
    "search_top_k",
]
