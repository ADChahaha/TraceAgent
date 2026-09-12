# test_async_execution

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

真实异步图与替身模型/工具 → 路由 protobuf 流 → 验证同一事件循环执行、逐项工具结果、共享超时和取消清理。

- `test_runtime_executes_model_and_tools_on_event_loop`：模型和工具在所属事件循环执行，事件编号连续。
- `test_model_cancellation_closes_provider_stream`：取消模型等待会关闭 provider 流。
- `test_async_tools_share_deadline_preserve_order_and_cancel_pending`：工具共享 deadline 并保持调用顺序，超时项被清理。
- `test_tool_result_streams_before_sibling_finishes_and_cancel_cleans_up`：快速工具先输出，关闭流清理慢工具且不再调用模型。
