# test_graph.py

执行链路：预设 provider 的标准 AIMessage → 真实 ChatModelFallbackChain 绑定工具 → 唯一 LangGraph 循环 → 工具执行与消息配对 → 图输出事件字典。测试只替换 provider 返回值，不另建 Agent 循环；对外 SSE 编码由 test_manager.py 覆盖。

- `test_run_completion_graph_stream_yields_objects_and_terminal_completion`：事件是字典，开始/索引/终态及序号正确，真实循环中的工具结果 ID 与模型调用配对。
- `test_run_completion_graph_stream_flushes_after_each_tool_call`：第一批事件输出时未提前调用下一轮模型。
- `test_run_completion_graph_stream_honors_external_should_stop`：正常执行完成，外部停止信号则产生取消终态。
- `test_should_stop_backfills_cancel_tool_replies_for_pending_tool_calls`：未执行工具在取消时得到失败回复。
- `test_should_stop_after_fulfilled_batch_does_not_duplicate_tool_replies`：已完成工具不重复补回复，只补未完成项。
