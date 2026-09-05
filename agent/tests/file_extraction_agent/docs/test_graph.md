# test_graph.py

消息执行链路：预设 provider 响应 → 正式 LangGraph → AIMessage/ToolMessage → manager 包装事件；取消在消息边界检查，已发布工具调用按 ID 配齐结果。

- `test_run_completion_graph_stream_yields_objects_and_terminal_completion`：正式模型/工具循环产出完整事件顺序，消息 ID 配对正确，包装层不预分配 SSE 序号。
- `test_tool_started_is_yielded_before_tool_execution`：工具结果执行前已向外产出开始调度事件。
- `test_cancel_before_execution_does_not_call_model`：早取消不调用 provider。
- `test_cancel_after_model_drains_tools_without_next_model`：模型调用已发布后取消，先返回工具回复且不请求下一轮模型。
- `test_interrupted_batch_backfills_only_pending_call_ids`：同名批次部分完成后异常，仅为剩余调用补失败；取消时用 cancelled 收口。
- `test_closing_event_stream_closes_message_generator`：外层关闭传播到消息生成器，停止后续调用。
