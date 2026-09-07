# test_schemas.py

这组测试覆盖文档问答的公开 schema：资源定位数组、append-only 历史消息、模型配置和工具执行超时。

实现链路：

```text
backend 传入 completion_id + resource_path(ResourceRefs) + messages
  -> DocumentQaCompletionRequest 校验资源定位数组（每项 type + location）
  -> DocumentQaMessage 保留 user/assistant/system/tool 消息和 assistant tool_calls
  -> 拒绝 memory 字段，避免每轮重写摘要破坏 prompt cache
  -> manager 用 ModelConfig 配置模型，graph 用 RunOptions 配置工具超时
```

强类型约定：`ResourceRefProtocol` 声明 type/location 结构，`ResourceRefs` 是其
Sequence 别名，agent_proto 的 ResourceRef 消息与 schemas.ResourceRef 均满足；
下游函数统一用 `ResourceRefs`，不出现 `Any`。

## 测试函数

- `test_completion_request_accepts_resource_path_and_append_only_messages`：验证 completion request 可以接收资源定位数组和 append-only 历史消息，并且对象上不再存在 memory 字段。
- `test_completion_request_rejects_memory_field`：验证 completion request 会拒绝 `memory` 字段。
- `test_completion_request_accepts_openai_tool_messages`：验证 completion request 可以直接接收 assistant tool_calls 和 tool role 消息。
- `test_completion_status_values_match_public_events`：验证 completion 状态枚举和公开事件语义一致。
- `test_model_config_keeps_model_transport_and_sampling_options`：验证模型配置保留 base URL、key、模型名、API transport、采样参数、重试和超时。
- `test_model_config_defaults_disable_sdk_retries_for_outer_backoff`：验证模型配置默认关闭 SDK 内部重试，默认使用 Responses API transport，并由外层 provider attempt 和随机指数退避统一控制。
- `test_run_options_only_configures_tool_timeout`：运行参数只有工具执行超时，默认 60 秒。
- `test_protocol_removes_tool_budget_without_reusing_field_number`：共享协议删除工具调用上限，保留原字段名和编号，超时继续使用编号 2。

请求改为资源定位数组 `resource_path`；不再向 manager 传 documents 或 task_id，历史消息与模型配置测试保留。

测试调用与替身模型名称同步采用 qa 命名，验证行为保持原契约。
