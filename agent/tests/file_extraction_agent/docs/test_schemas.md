# 问答契约测试

普通消息和配置 → DocumentQaMessage 校验角色/正文/工具 ID → application 与 graph 使用配置。
旧请求容器与状态枚举已移除，请求级校验由 application 测试覆盖。

- `test_message_accepts_tool_history`：工具调用和结果保留相同 ID。
- `test_message_rejects_invalid_content_or_extra_fields`：拒绝空正文、缺少工具 ID 和额外字段。
- `test_model_config_keeps_model_transport_and_sampling_options`：保留模型、传输、采样及兼容配置字段。
- `test_model_config_defaults_disable_sdk_retries_for_outer_backoff`：默认传输为 Responses，兼容重试字段默认零。
- `test_run_options_only_configures_tool_timeout`：运行选项仅有工具超时，默认 60 秒。
- `test_protocol_removes_tool_budget_without_reusing_field_number`：旧工具预算字段名及编号保留，超时继续使用编号 2。
