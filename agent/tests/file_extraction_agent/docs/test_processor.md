# test_processor.py

这份测试覆盖 `file_extraction_agent.processor` 入口和默认模型配置读取。测试重点是确认抽取入口只负责组装输入并调用图执行器，模型连接配置由 `impl/model_factory.py` 从显式参数或 agent 进程环境中归一化。

## 测试函数

- `test_extract_builds_input_models_and_runs_graph`：用 fake model builder 和 fake graph 确认 `extract(...)` 会把 HTML、字段定义和 stage model 正确传给抽取图。
- `test_normalize_model_config_loads_default_env_file`：确认未显式传入 `model_config` 时，会从候选 `.env` 读取 `BASE_URL`、`OPENAI_API_KEY`、阶段模型名和采样参数。
- `test_normalize_model_config_ignores_generic_api_key_env`：确认通用 `API_KEY` 不再作为环境变量 fallback，避免和其他服务密钥混用；默认密钥入口只保留 `OPENAI_API_KEY`。
