# 工具 embedding 缓存测试

生成端准备真实资源发布到 storage 服务 → open_workspace 创建工具上下文 → embedding.py 加载并缓存索引 → `search_embedding` 组装 worker 请求（每轮串行启动子进程）。

- `test_resource_reuses_vectors_and_preserves_paths`：跨轮复用向量和引用路径，同轮复用索引对象，读取不调用生成端模型；covered_files 现在是以 `documents/` 开头的桶内 key。
- `test_query_uses_recorded_model_after_env_change`：worker 请求使用资源清单记录的 `model_id`，环境变量变化不覆盖。
- `test_parallel_queries_load_index_once_and_serialize_worker`：同轮并行查询只执行一次 `np.load` 加载索引，且 worker 启动串行（最大并发为 1）。
