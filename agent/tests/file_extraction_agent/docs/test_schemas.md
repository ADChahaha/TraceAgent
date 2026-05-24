# test_schemas.py

这组测试覆盖 `document-qa chat/completions` 的公开 schema。schema 不再描述字段抽取任务，而是描述一次 QA completion 所需的文档、append-only 历史消息、模型配置和运行预算。

实现链路：

```text
backend 传入 completion_id + documents + messages
  -> DocumentQaCompletionRequest 校验每个 document 的 filename/html
  -> DocumentQaMessage 保留 user/assistant/system/tool 消息和 assistant tool_calls
  -> 拒绝 memory 字段，避免每轮重写摘要破坏 prompt cache
  -> processor 用 RunOptions 和 ModelConfig 继续控制模型与工具预算
```

## 测试函数

- `test_completion_request_accepts_documents_and_append_only_messages`：验证 completion request 可以接收多文档和 append-only 历史消息，并且对象上不再存在 memory 字段。
- `test_completion_request_rejects_memory_field`：验证 completion request 会拒绝 `memory` 字段。
- `test_completion_request_accepts_openai_tool_messages`：验证 completion request 可以直接接收 assistant tool_calls 和 tool role 消息。
- `test_completion_status_values_match_public_events`：验证 completion 状态枚举和公开事件语义一致。
- `test_model_config_keeps_model_transport_and_sampling_options`：验证模型配置保留 base URL、key、模型名、API transport、采样参数、重试和超时。
- `test_model_config_defaults_disable_sdk_retries_for_outer_backoff`：验证模型配置默认关闭 SDK 内部重试，默认使用 Responses API transport，并由外层 provider attempt 和随机指数退避统一控制。
- `test_run_options_defaults_to_tool_budget_only`：验证运行预算默认只保留工具调用上限。
