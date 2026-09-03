# test_graph.py

这份测试覆盖 QA completion 事件流的 SSE 输出。事件流的组装与收口函数
`run_completion_graph_stream` 已收敛到 `manager`（它负责把 completion 创建、
source index、模型消息、工具调用和终态事件按顺序写出并选终态），`core/graph.py`
只保留 `GraphState` 与 `build_graph_state` 状态定义。

实现链路：

```text
GraphState + resolution_model
  -> manager.run_completion_graph_stream
  -> completion.created
  -> source_indexed(workspace_root + tree，其中 workspace_root 是每个 completion 的文件树根，
      tree 是逐层缩进的目录/文件清单)
  -> model_message / tool_started / tool_completed 循环
  -> completion.completed
```

说明：`source_indexed` 不再带 `source_selectors`（旧 `path_id -> 原始 DOM id`
映射已删除），改为暴露文件树根目录路径和逐层清单。测试里的 `prepare_completion_state`
输入已全部强类型化（`list[InputDocument]` / `list[DocumentQaMessage]`），直接产出 `GraphState`。

## 测试函数

- `test_run_completion_graph_stream_yields_sse_events_and_terminal_completion`：验证 graph 输出标准 SSE 事件，先创建 completion，再输出 source index、模型/工具事件，最后以 `completion.completed` 收口，并保持 seq 连续递增；`source_indexed` 暴露 `workspace_root` 和 `tree`。
- `test_run_completion_graph_stream_flushes_after_each_tool_call`：验证 graph 会在每次工具调用前后持续 flush 事件，而不是等整轮 QA 完成后批量返回。
- `test_run_completion_graph_stream_honors_external_should_stop`：验证 `run_completion_graph_stream` 接受可选的 `should_stop` 回调 —— 回调返回 False 时按正常流程以 `completion.completed` 收口；回调返回 True 时中断循环并改以 `completion.cancelled` 收口。取消判定因此外置到调用方。
- `test_should_stop_backfills_cancel_tool_replies_for_pending_tool_calls`：验证 `should_stop` 触发时若最后产出的 provider 消息带有尚未执行的 `tool_calls`，`_backfill_pending_tool_cancels` 会为每个未配对 tool 补一条 `ok:false` / "tool execution cancelled" 的 `tool_completed` 回复，再以 `completion.cancelled` 收口，避免悬垂 tool_call。
- `test_should_stop_after_fulfilled_batch_does_not_duplicate_tool_replies`：验证 `_backfill_pending_tool_cancels` 只对「已产出但未配对」的 tool_call 补取消回复，不会重复给已经跑成功的 tool 追加结果。
