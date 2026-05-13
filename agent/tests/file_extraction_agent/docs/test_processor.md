# test_processor.py

这份测试覆盖 `file_extraction_agent.processor` 的 stream-first 入口和模型配置读取。入口负责把 `documents`、`task_spec` 和模型配置组装成图输入，然后把图执行器产出的 NDJSON 原样向外迭代。

## 测试函数

- `test_extract_stream_builds_documents_input_and_runs_stream_graph`：用 fake model builder 和 fake stream graph 确认 `extract_stream(...)` 会传递 documents、字段定义和 resolution model。
- `test_normalize_model_config_loads_default_env_file`：确认未显式传入模型配置时，会从候选 `.env` 读取连接、模型、采样和超时配置。
- `test_normalize_model_config_rejects_unknown_model_fields`：确认旧 broad 模型字段仍会被拒绝。
