# 向量算法测试

文档分块与索引构建使用生成端实现；`search_top_k` 使用 Agent 的 `tools/embedding.py`，验证磁盘格式对应的数据可被查询端消费。

文本与字符偏移 → 固定 token 窗口分块 → 替身模型编码 → 余弦排序，验证生成端分块/构建与工具侧检索的衔接。

- `test_chunk_text_slides_with_fixed_window_and_overlap`：窗口大小和重叠按配置滑动。
- `test_chunk_text_uses_token_offsets_for_text`：根据 token 字符偏移提取原文。
- `test_build_index_records_document_and_coverage`：记录源文档和覆盖文件。
- `test_build_index_chunk_crosses_md_blocks`：一个 chunk 可以跨多个 Markdown 块。
- `test_search_top_k_returns_descending_score_with_payload`：按得分降序返回文本和引用。
- `test_search_top_k_respects_top_k_limit`：限制返回数量。
- `test_search_top_k_returns_all_when_top_k_exceeds_chunks`：数量超过候选时返回全部。
- `test_build_index_aggregates_vectors_per_chunk`：每个 chunk 对应一个向量。
