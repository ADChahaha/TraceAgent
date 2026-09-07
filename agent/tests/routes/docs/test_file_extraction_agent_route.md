# 问答 gRPC 测试

真实客户端 → protobuf 请求转换与校验 → CompletionManager/Runtime → protobuf 事件流。模型和资源预检使用替身，保留真实线程、注册表和网络传输。

- `test_chat_streams_typed_events_and_preserves_json`：事件按序逐条传输，动态 JSON 保留大整数、空值和特殊字符。
- `test_chat_preserves_history_options_and_model_defaults`：历史工具消息、显式零值和未传配置的默认值保持一致。
- `test_chat_model_override_precedence`：兼容扁平模型参数，嵌套模型配置优先。
- `test_chat_rejects_invalid_input_before_first_event`：无效 ID、角色、历史工具 JSON 或空消息在首事件前返回 INVALID_ARGUMENT。
- `test_chat_runtime_failure_is_terminal_event`：开始执行后的异常通过 completion.failed 保留原始错误文本。
- `test_cancel_returns_before_tool_batch_and_stream_drains`：取消 RPC 先返回 cancelling，工具结果补齐后原流仅发一个取消终态。
- `test_transport_cancel_or_deadline_cleans_runtime`：RPC 取消和超时唤醒阻塞消费者并释放注册项，后台观察停止信号。
- `test_duplicate_id_does_not_cancel_existing_stream`：重复 ID 请求失败，原运行时仍可独立取消。
- `test_cancel_unknown_and_get_placeholder`：未知取消返回 not_found，查询接口保留 not_implemented。
- `test_legacy_request_fields_are_not_in_protocol`：检查 protobuf 字段集合，新契约只接收资源路径，不定义旧业务字段。
