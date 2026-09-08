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
- `test_cancel_unknown_returns_not_found`：未知取消返回 not_found。
- `test_completion_query_is_not_exposed`：共享协议及客户端不暴露问答查询，旧 RPC 路径返回 UNIMPLEMENTED。
- `test_legacy_request_fields_are_not_in_protocol`：检查 protobuf 字段集合，新契约只接收资源路径，不定义旧业务字段。

## 异步并发与关闭回归

- `test_many_waiting_streams_keep_control_rpcs_available`：二十条问答流同时等待时，取消 RPC 仍可响应，流数量不受旧 worker 槽限制。
- `test_initialization_cleanup_survives_event_loop_shutdown`：初始化期间客户端取消，随后事件循环关闭，迟到的初始化结果仍会释放注册项。

事件替身使用异步生成器，与生产协程一致；同步 RPC 客户端的跨线程测试信号通过 await 等待。
运行参数的显式零值使用 `tool_execution_timeout=0` 验证；工具调用上限已从共享协议删除。
# 原生流式回归

`test_real_graph_streams_native_chunks_and_retry_over_rpc`：真实 LangGraph 与 LangChain 回调进入 RPC，验证增量先于生成结束、首次随机退避为 375–500 ms、尝试 ID 隔离和业务取消的唯一终态。
