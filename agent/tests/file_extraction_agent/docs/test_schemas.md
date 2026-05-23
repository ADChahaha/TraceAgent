# test_schemas.py

这组测试覆盖 `document-qa chat/completions` 的公开 schema。schema 不再描述字段抽取任务，而是描述一次 QA completion 所需的文档、历史消息、压缩记忆、模型配置和运行预算。

实现链路：

```text
backend 传入 completion_id + documents + messages + memory
  -> DocumentQaCompletionRequest 校验每个 document 的 filename/html
  -> DocumentQaMessage 保留 user/assistant/system/tool 消息和 assistant tool_calls
  -> DocumentQaMemory 为 reading_history/evidence_notes/prior_answers/open_threads 提供空列表默认值
  -> processor 用 RunOptions 和 ModelConfig 继续控制模型与工具预算
```

## 测试函数

- `test_completion_request_accepts_documents_messages_and_memory`：验证 completion request 可以接收多文档、历史消息和压缩记忆，并归一成公开 schema 对象。
- `test_completion_request_accepts_openai_tool_messages`：验证 completion request 可以直接接收 assistant tool_calls 和 tool role 消息。
- `test_memory_defaults_to_empty_lists`：验证 memory 默认不会共享可变列表，缺省时四类记忆都是空列表。
- `test_completion_status_values_match_public_events`：验证 completion 状态枚举和公开事件语义一致。
- `test_model_config_keeps_resolution_model_and_sampling_options`：验证模型配置仍保留 base URL、key、模型名、采样参数、重试和超时。
- `test_model_config_defaults_disable_sdk_retries_for_outer_backoff`：验证模型配置默认关闭 SDK 内部重试，由外层 provider attempt 和随机指数退避统一控制。
- `test_run_options_defaults_to_tool_budget_only`：验证运行预算默认只保留工具调用上限。
