# test_processor.py

这份测试覆盖 `file_extraction_agent.processor` 的 QA completion 入口和模型配置读取。入口负责把 `completion_id`、`documents`、`messages`、`memory` 和模型配置组装成图输入，然后把图执行器产出的 SSE 原样向外迭代。

实现链路：

```text
create_completion_stream(...)
  -> build_completion_input(...)
  -> build_resolution_model(model_config)
  -> run_completion_graph_stream(completion_input, resolution_model)
  -> 逐条 yield SSE 文本
```

## 测试函数

- `test_create_completion_stream_builds_completion_input_and_runs_graph`：用 fake model builder 和 fake stream graph 确认 `create_completion_stream(...)` 会传递 completion id、documents、messages 和 resolution model。
- `test_create_completion_stream_validates_input_before_iteration`：确认 completion 输入校验发生在返回 SSE iterator 前，route 层可以把业务入参错误稳定映射为 422。
- `test_create_completion_stream_registers_active_completion_before_iteration`：确认 active completion 会在返回 iterator 前注册，backend 立即调用 cancel 时不会因为流还没开始迭代而得到 `not_found`。
- `test_normalize_model_config_loads_default_env_file`：确认模型配置能从 `.env` 中读取 base URL、key、模型名、采样参数、推理强度、重试次数和超时。
- `test_build_chat_model_builds_responses_stream_then_chat_fallbacks`：确认 resolution chat model 会按 `responses_stream -> chat_completions_stream -> responses_invoke -> chat_completions_invoke` 构造四级 fallback，默认优先 Responses API 和 stream，失败后再退到 chat/completions 与非流调用。
- `test_normalize_model_config_rejects_unknown_model_fields`：确认模型配置拒绝未知字段，避免旧 broad/resolution 多阶段配置重新进入 QA completion 入口。
