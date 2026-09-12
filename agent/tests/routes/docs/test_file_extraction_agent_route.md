# test_file_extraction_agent_route

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

真实 gRPC 客户端 → 路由适配参数 → application 校验与依赖装配 → 业务事件经 路由编码函数 编码 protobuf；同时用真实 LangGraph 验证增量、重试和取消。

- `test_real_graph_streams_native_chunks_and_retry_over_rpc`：真实图和模型回调 → RPC 增量；验证重试字段及生成期间业务取消。
- `test_chat_streams_typed_events_and_preserves_json`：事件按序逐条传输，动态 JSON 保留大整数、空值和特殊字符。
- `test_chat_preserves_history_options_and_model_defaults`：历史工具消息、显式零值和未传配置的默认值保持一致。
- `test_chat_model_override_precedence`：兼容扁平模型参数，嵌套模型配置优先。
- `test_chat_rejects_invalid_input_before_first_event`：无效 ID、角色、历史工具 JSON 或空消息在首事件前返回 INVALID_ARGUMENT。
- `test_chat_runtime_failure_is_terminal_event`：开始执行后的异常通过 completion.failed 保留原始错误文本。
- `test_legacy_request_fields_are_not_in_protocol`：新契约只接收资源路径，不定义旧业务字段。
- `test_protobuf_encoding_failure_is_terminal_and_closes`：protobuf 无法编码非法 UTF-8 时，业务流输出连续编号的唯一失败终态并关闭 core。
