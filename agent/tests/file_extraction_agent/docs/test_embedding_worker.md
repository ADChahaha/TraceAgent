# test_embedding_worker.py

验证检索 worker 的请求解析、top-k 输出与真实子进程入口。

## 实现链路

```text
worker.search(request)
  -> 校验 query / chunks / dimension / vectors_b64 长度与有限性
  -> OpenVinoQueryEmbedder(model_id) 编码 query 并归一化
  -> scores = vectors @ query -> 取 top_k
  -> {ok, query, results:[{score, document, chunk_id, text, token_range, covered_files}]}

python -m service.file_extraction_agent.core.tools.worker
  -> 读 stdin JSON -> search -> 以 UTF-8 写 stdout JSON；异常转 {"ok": false, ...}
```

## 测试函数

- `test_search_returns_top_k_with_fields`：替身编码器下按相似度取 top-k，字段（score/covered_files/token_range）完整。
- `test_search_rejects_bad_vectors`：`vectors_b64` 长度与 dimension 不匹配时返回 `ok: false`。
- `test_search_rejects_empty_query`：空 query 返回错误。
- `test_worker_subprocess_entry_with_real_model`：本地模型缓存存在时以真实子进程跑请求，返回 3 条结果（响应为 UTF-8）。
