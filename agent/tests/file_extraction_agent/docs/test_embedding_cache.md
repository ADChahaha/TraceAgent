# 工具 embedding 缓存测试

生成端准备真实资源 → open_workspace 创建工具上下文 → embedding.py 加载索引与查询模型 → 仅编码 query 并检索。

- `test_resource_reuses_vectors_and_preserves_paths`：跨轮复用磁盘向量和引用路径，同轮复用索引对象，读取不调用生成端模型。
- `test_query_uses_recorded_model_after_env_change`：环境变化不覆盖资源清单配置，仅将查询文本交给模型。
- `test_parallel_queries_share_tool_model_and_index`：同轮并行查询只加载一次模型与索引，全部得到成功结果。
