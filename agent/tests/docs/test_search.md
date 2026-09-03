# test_search.py

这组测试验证 `service.file_extraction_agent.core.tools.embedding.search` 的向量索引与检索纯逻辑。**不依赖真实 embedding 模型或 OpenVINO**：embedder 和 tokenize 都是可注入替身，只验证分块、覆盖关系与 top-k 排序这些行为。

实现链路：

```text
streams: {document_name: [(md_path, text), ...]}
  -> 假 embedder（按字符串特征返回固定向量）编码每个 chunk
  -> 假 tokenize（每个字符一个 token，带字符 offsets）
  -> build_index(...) 产出 EmbeddingIndex(chunks, vectors)
  -> search_top_k(query_vec, index, top_k) 做余弦检索
```

## 测试函数

- `test_chunk_text_slides_with_fixed_window_and_overlap`：验证 `chunk_text` 按 `chunk_size=8, overlap=2` 滑窗时，token_range 从 `(0,8)` 到 `(6,14)` 再到 `(12,20)`，步进 `chunk_size-overlap=6`，且最后一窗不越界。
- `test_chunk_text_uses_token_offsets_for_text`：验证 chunk 的 `text` 用 token 的字符 offsets 切（如 4 token 窗口切出 `abcd`/`efgh`/`ij`），而不是按 token 数硬切。
- `test_build_index_records_document_and_coverage`：验证 `build_index` 对单个文档（整段作为一个 chunk）记录 `model_id`、`document=contract.pdf`，且向量行数与 chunk 数一致。
- `test_build_index_chunk_crosses_md_blocks`：验证大窗口 chunk 能横跨多个 `.md` 块，`covered_files` 列出该 chunk 覆盖的所有 `.md` 路径。
- `test_search_top_k_returns_descending_score_with_payload`：验证 `search_top_k` 返回按分数降序的结果，且每项含 `text`/`document`/`covered_files`/`chunk_id`，`text` 非空。
- `test_search_top_k_respects_top_k_limit`：验证 `top_k` 未超过 chunk 数时精确返回 `top_k` 条。
- `test_search_top_k_returns_all_when_top_k_exceeds_chunks`：验证 `top_k` 超过 chunk 数时返回全部可用 chunk，且仍按分数降序。
- `test_build_index_aggregates_vectors_per_chunk`：验证多文档输入时，chunk 按文档归属，`document` 集合与输入文档一致，向量数等于文档数。
