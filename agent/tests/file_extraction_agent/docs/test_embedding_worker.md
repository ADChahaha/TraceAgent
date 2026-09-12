# test_embedding_worker.py

验证统一工具子进程（worker）的 operation 分发、请求校验、prepare 产物与真实入口。

## 实现链路

```text
worker.handle({operation, args, workspace})
  -> operation 不在已知集合 -> unknown operation
  -> prepare：按 resource_path 拉取归档并校验索引 -> {ok, workspace}
  -> ls / grep / read：从 workspace payload 重建文档树后执行同步 helper
  -> search_embedding：从 workspace.index 解码 chunks/vectors
       -> OpenVinoQueryEmbedder(model_id) 编码 query 并归一化
       -> scores = vectors @ query -> 取 top_k

python -m service.file_extraction_agent.core.tools.worker
  -> 读 stdin JSON -> handle -> 以 UTF-8 写 stdout JSON；异常转 {"ok": false, ...}
```

## 测试函数

- `test_handle_rejects_unknown_operation`：未知 operation 返回错误，不进入任何资源访问。
- `test_search_returns_top_k_with_fields`：替身编码器下按相似度取 top-k，字段（score/covered_files/token_range）完整。
- `test_search_rejects_bad_vectors`：`vectors_b64` 长度与 dimension 不匹配时返回 `ok:false`。
- `test_search_rejects_empty_query`：空 query 返回错误。
- `test_prepare_returns_workspace_payload`：prepare 返回 bucket、归档 bytes 和已解析（`documents/...`）的索引。
- `test_prepare_rejects_missing_locations`：空 resource_path 返回 `kind=invalid`。
- `test_handle_reads_from_workspace_payload`：用 prepare 产物执行 ls/read，不访问 storage 服务也能读出正文。
- `test_worker_subprocess_entry_with_real_model`：本地模型缓存存在时以真实子进程跑检索，返回 3 条结果（响应为 UTF-8）。
