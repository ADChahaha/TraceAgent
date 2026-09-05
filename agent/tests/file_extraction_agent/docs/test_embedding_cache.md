# 资源索引复用测试

资源准备 → 两轮加载同一路径 → 使用清单模型编码查询，不再通过任务 ID 查找缓存。

- `test_resource_reuses_vectors_and_preserves_paths`：加载不调用 embedding，向量和引用路径保持一致，图状态没有管理 ID。
- `test_query_uses_recorded_model_after_env_change`：环境配置变化后仍使用资源记录的模型和后端，只编码 query。
