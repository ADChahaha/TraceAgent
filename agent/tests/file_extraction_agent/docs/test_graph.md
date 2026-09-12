# test_graph.py

消息执行链路：预设 provider 响应 → 正式 LangGraph → AIMessage/ToolMessage → turn_stream 包装事件；取消沿 Task 传播，关闭生成器后不再请求后续模型。

- `test_stream_completion_events_yields_objects_and_terminal_completion`：正式模型/工具循环产出完整事件顺序，消息 ID 配对正确，包装层不预分配 SSE 序号。
- `test_tool_started_is_yielded_before_tool_execution`：工具结果执行前已向外产出开始调度事件。
- `test_cancel_before_execution_does_not_call_model`：早取消不调用 provider。
- `test_cancel_after_model_skips_tools_and_next_model`：模型调用已发布后取消，跳过工具执行且不请求下一轮模型。
- `test_executor_failure_returns_entire_failed_batch`：executor.py 执行器整体异常时返回完整失败批次；取消消费 Task 后不再调用模型，否则允许模型解释失败。
- `test_executor_failure_preserves_published_results`：工具结果先发布、执行器随后异常时，保留已发布成功或失败消息的全部内容；仅为剩余项补失败，对外不重复输出，模型历史仍按原调用顺序排列。
- `test_closing_event_stream_closes_message_generator`：外层关闭传播到消息生成器，停止后续调用。

事件链路测试使用 conftest 生成的 resource_path 作为 workspace 传入，并用替身工具替换 `loop.build_tools`，避免为事件映射测试启动真实工具子进程；turn_stream 只发出启动确认和消息事件，事件包装入口不接收 completion ID。独立图契约测试注入执行器，直接验证节点行为。

测试使用协程与异步迭代器驱动实际 Agent 链路；模型替身提供 astream/ainvoke，取消等待使用事件循环。

## graph 独立契约

- `test_graph_task_cancellation_cleans_active_node`：取消图执行 Task，分别验证模型和工具等待被清理且不进入后续调用。
- `test_graph_rejects_invalid_tool_ids_before_execution`：空 ID 或重复 ID 在图内报错，工具不会执行。

流式契约同步：模型输出按 started → delta → done 验证，工具结果仍按调用 ID 配对。

模型装配对象重命名为 ConfiguredChatModel，明确只保存一个固定调用配置。

图的模型和工具等待响应 Task.cancel，清理后不进入下一节点。

本轮契约调整：内层只输出普通 Agent 事件；完成/失败由 stream_completion 唯一出口生成，取消直接传播且不输出 cancelled。对应测试使用图输出或外层流验证，保留配对、重试和资源清理覆盖。

模型替身直接保存单个 provider 与 use_stream，构建测试通过延迟加载工厂注入模型类。

取消测试使用 Task.cancel()/流关闭，移除 should_stop 标志；保留失败工具批次与发布结果覆盖。

事件流模块引用同步为 turn_stream；仅重命名，不改变测试目标行为。
