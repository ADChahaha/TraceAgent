# test_async_execution

真实图 → 异步模型/并行工具 → 逐项事件；关闭流或取消任务后验证下层清理。

- `test_runtime_executes_model_and_tools_on_event_loop`：模型和工具在所属事件循环执行，事件编号连续。
- `test_model_cancellation_closes_provider_stream`：取消模型等待会关闭 provider 流。
- `test_async_tools_share_deadline_preserve_order_and_cancel_pending`：工具共享 deadline 并保持调用顺序，超时项被清理。
- `test_tool_result_streams_before_sibling_finishes_and_cancel_cleans_up`：快速工具先输出，关闭流清理慢工具且不再调用模型。

执行入口改为直接消费 stream_completion(...) 异步生成器，不创建运行时对象。
