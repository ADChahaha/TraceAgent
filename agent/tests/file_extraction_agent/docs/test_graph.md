# test_graph

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

预设模型响应与替身工具 → 真实 LangGraph → core 输出 → 路由 protobuf 流；验证调用历史、事件顺序、执行器异常和取消。

- `test_stream_completion_yields_protobuf_and_terminal_completion`：真实模型/工具循环经业务事件经适配器输出 protobuf，验证完整事件顺序、连续序号和工具历史。
- `test_tool_started_is_yielded_before_tool_execution`：工具结果执行前已向外产出开始调度事件。
- `test_cancel_before_execution_does_not_call_model`：早取消不调用 provider。
- `test_cancel_after_model_skips_tools_and_next_model`：模型调用已发布后取消，跳过工具执行且不请求下一轮模型。
- `test_executor_failure_returns_entire_failed_batch`：executor.py 执行器整体异常时返回完整失败批次；取消消费 Task 后不再调用模型，否则允许模型解释失败。
- `test_executor_failure_preserves_published_results`：工具结果先发布、执行器随后异常时，保留已发布成功或失败消息的全部内容；仅为剩余项补失败，对外不重复输出，模型历史仍按原调用顺序排列。
- `test_closing_event_stream_closes_message_generator`：外层关闭传播到消息生成器，停止后续调用。
- `test_graph_task_cancellation_cleans_active_node`：取消图执行 Task，分别验证模型和工具等待被清理且不进入后续调用。
- `test_graph_rejects_invalid_tool_ids_before_execution`：空 ID 或重复 ID 在图内报错，工具不会执行。
