"""Tests for embedding search helpers (build_index / chunk_text / search_top_k).

这些测试不依赖真实 embedding 模型或 OpenVINO：embedder 和 tokenizer 都是
可注入的替身，只验证检索索引的分块覆盖与 top-k 排序等纯逻辑行为。
"""
from __future__ import annotations

import numpy as np
import pytest
from service.file_extraction_agent.core.tools.embedding import search_top_k

from service.document_resources.search import (
    Chunk,
    EmbeddingIndex,
    build_index,
    chunk_text,
)


class _FakeEmbedder:
    """返回与文本对应的固定向量的假 embedder（按字符串长度区分）。"""

    dim = 3

    def encode(self, texts):
        vectors = []
        for text in texts:
            n = sum(ord(ch) for ch in text) or 1
            vectors.append([float(n % 2), float(len(text) % 3), float(n % 5)])
        return np.array(vectors, dtype=np.float32)


def _fake_tokenize(text):
    """把文本按字符拆成带 offsets 的 token（每个字符一个 token）。"""
    return [(i, i + 1) for i in range(len(text))]


def _segments():
    return [
        ("/abs/0001/docs/0001-termination.md", "Either party may terminate with notice."),
        ("/abs/0001/docs/0002-notice.md", "Notice must be written in the same language."),
        ("/abs/0001/docs/0003-terms.md", "Payment is due within 30 days."),
    ]


def _stream():
    return {"contract.pdf": _segments()}


def test_chunk_text_slides_with_fixed_window_and_overlap():
    text = "abcdefghijklmnopqrstuvwxyz"
    spans = chunk_text(text, tokenize=_fake_tokenize, chunk_size=8, overlap=2)
    assert spans[0].token_range == (0, 8)
    assert spans[1].token_range == (6, 14)
    assert spans[2].token_range == (12, 20)
    assert spans[-1].token_range[-1] <= len(text)


def test_chunk_text_uses_token_offsets_for_text():
    text = "abcdefghij"
    spans = chunk_text(text, tokenize=_fake_tokenize, chunk_size=4, overlap=0)
    assert spans[0].text == "abcd"
    assert spans[1].text == "efgh"
    assert spans[2].text == "ij"


def test_build_index_records_document_and_coverage(tmp_path):
    result = build_index(
        _stream(),
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=200,
        overlap=0,
    )
    assert result.model_id == "fake-a8m"
    assert len(result.chunks) == 1
    assert all(chunk.document == "contract.pdf" for chunk in result.chunks)
    assert result.vectors.shape[0] == len(result.chunks)


def test_build_index_chunk_crosses_md_blocks(tmp_path):
    # chunk 窗口足够大，跨越多个 .md 块 -> covered_files 应列出多个文件
    result = build_index(
        _stream(),
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=200,
        overlap=0,
    )
    assert len(result.chunks) == 1
    assert set(result.chunks[0].covered_files) >= {
        "/abs/0001/docs/0001-termination.md",
        "/abs/0001/docs/0002-notice.md",
        "/abs/0001/docs/0003-terms.md",
    }


def test_search_top_k_returns_descending_score_with_payload(tmp_path):
    index = build_index(
        _stream(),
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=12,
        overlap=0,
    )
    query_vec = np.array([[1.0, 0.0, 1.0]], dtype=np.float32)
    results = search_top_k(query_vec, index, top_k=2)
    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"]
    for item in results:
        assert "text" in item
        assert "document" in item
        assert "covered_files" in item
        assert "chunk_id" in item
        assert item["text"]


def test_search_top_k_respects_top_k_limit(tmp_path):
    index = build_index(
        _stream(),
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=200,
        overlap=0,
    )
    query_vec = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    assert len(search_top_k(query_vec, index, top_k=1)) == 1
    assert len(search_top_k(query_vec, index, top_k=5)) == 1


def test_search_top_k_returns_all_when_top_k_exceeds_chunks(tmp_path):
    index = build_index(
        _stream(),
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=30,
        overlap=0,
    )
    query_vec = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    results = search_top_k(query_vec, index, top_k=5)
    assert len(results) <= 5
    assert results[0]["score"] >= results[-1]["score"]


def test_build_index_aggregates_vectors_per_chunk(tmp_path):
    stream = {"a.pdf": _segments(), "b.pdf": _segments()}
    result = build_index(
        stream,
        embedder=_FakeEmbedder(),
        model_id="fake-a8m",
        tokenize=_fake_tokenize,
        chunk_size=200,
        overlap=0,
    )
    assert len(result.chunks) == 2
    assert {chunk.document for chunk in result.chunks} == {"a.pdf", "b.pdf"}
    assert result.vectors.shape[0] == 2
