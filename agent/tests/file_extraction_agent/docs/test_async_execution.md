# 异步 Agent 执行测试

真实资源与异步模型/工具替身 → LangGraph 异步节点 → 运行时事件流，验证实际执行发生在事件循环内。

- `test_runtime_executes_model_and_tools_on_event_loop`：模型和工具均在消费流的事件循环执行，完成一轮工具调用并输出有序终态。
- `test_model_cancellation_closes_provider_stream`：取消模型调用协程会关闭供应商流，不继续降级重试。
- `test_async_tools_share_deadline_preserve_order_and_cancel_pending`：工具协程并发执行，共享超时，按调用顺序返回，慢调用取消后运行清理。

- `test_tool_result_streams_before_sibling_finishes_and_cancel_cleans_up`：慢工具阻塞时先收到快工具结果，取消后慢工具执行 finally，不再调用模型、不补造结果且只有一个取消终态。
