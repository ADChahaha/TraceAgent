# test_processor.py

这份测试覆盖 `file_extraction_agent.processor` 入口和默认模型配置读取。测试重点是确认抽取入口只负责组装输入并调用图执行器，模型连接配置由 `impl/model_factory.py` 从显式参数或 agent 进程环境中归一化。

## 测试函数

- `test_extract_builds_input_models_and_runs_graph`：用 fake model builder 和 fake graph 确认 `extract(...)` 会把 HTML、字段定义和 resolution model 正确传给抽取图。
- `test_normalize_model_config_loads_default_env_file`：确认未显式传入 `model_config` 时，会从候选 `.env` 读取 `BASE_URL`、`OPENAI_API_KEY`、阶段模型名、采样参数、重试次数和请求超时。
- `test_normalize_model_config_ignores_generic_api_key_env`：确认通用 `API_KEY` 不再作为环境变量 fallback，避免和其他服务密钥混用；默认密钥入口只保留 `OPENAI_API_KEY`，并使用默认重试配置。
- `test_normalize_model_config_rejects_unknown_model_fields`：确认模型配置会拒绝未知字段，避免旧 broad 兼容字段重新进入抽取链路。
- `test_build_chat_model_passes_retry_and_timeout`：确认 `model_factory` 创建 `ChatOpenAI` 时会传入 `max_retries` 和 `request_timeout`。
- `test_build_chat_model_passes_sampling_parameters_without_model_kwargs`：确认 `top_p` 作为 `ChatOpenAI` 显式参数传入，`top_k` 放进兼容接口使用的 `extra_body`，避免通过 `model_kwargs` 变成不被服务端接受的请求参数。
