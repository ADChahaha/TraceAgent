# test_graph.py

消息执行链路：预设 provider 响应 → 正式 LangGraph → AIMessage/ToolMessage → completion_runtime 包装事件；取消在节点边界检查，取消后不启动新工具、不交付迟到结果。

- `test_stream_completion_events_yields_objects_and_terminal_completion`：正式模型/工具循环产出完整事件顺序，消息 ID 配对正确，包装层不预分配 SSE 序号。
- `test_tool_started_is_yielded_before_tool_execution`：工具结果执行前已向外产出开始调度事件。
- `test_cancel_before_execution_does_not_call_model`：早取消不调用 provider。
- `test_cancel_after_model_skips_tools_and_next_model`：模型调用已发布后取消，跳过工具执行且不请求下一轮模型。
- `test_executor_failure_returns_entire_failed_batch`：executor.py 执行器整体异常时返回完整失败批次；取消后不再调用模型，否则允许模型解释失败。
- `test_closing_event_stream_closes_message_generator`：外层关闭传播到消息生成器，停止后续调用。

事件链路测试使用 conftest 生成的 resource_path；图执行通过工具层读取文件，completion_runtime 只发出启动确认和消息事件，事件包装入口不接收 completion ID。独立图契约测试注入执行器，直接验证节点行为。

测试使用协程与异步迭代器驱动实际 Agent 链路；模型替身提供 astream/ainvoke，取消等待使用事件循环。

## graph 独立契约

- `test_graph_checks_cancellation_before_each_node`：直接运行编译图，覆盖模型前、模型中、模型输出后及工具批次后取消；模型输出后取消会跳过工具，工具结束后取消不再调用模型。
- `test_graph_rejects_invalid_tool_ids_before_execution`：空 ID 或重复 ID 在图内报错，工具不会执行。

流式契约同步：模型输出按 started → delta → done 验证，工具结果仍按调用 ID 配对。

模型装配对象重命名为 ConfiguredChatModel，明确只保存一个固定调用配置。

图在每个节点启动前检查取消；模型输出后取消不启动工具；已取消时不再交付失败工具结果。
