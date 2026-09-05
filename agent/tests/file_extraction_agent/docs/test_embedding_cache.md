# test_embedding_cache.py

相同任务的不同 completion → 同一文档版本命中磁盘缓存 → 不重复编码 → 引用路径映射到当前 workspace。

- `test_task_cache_reuses_vectors_and_rebases_paths`：验证同任务跨轮只编码一次、引用指向当前文件；不同任务或文档内容变更重新编码。
