# test_graph.py

这份测试覆盖 QA completion graph 的 SSE 输出。graph 负责把 completion 创建、source index、模型消息、工具调用和终态完成事件按顺序写出。

实现链路：

```text
DocumentQaCompletionInput + resolution_model
  -> run_completion_graph_stream
  -> completion.created
  -> source_indexed(document_tree + source_selectors，其中 document/section header 和可读 block 都可定位)
  -> model_message / tool_started / tool_completed 循环
  -> completion.completed
```

## 测试函数

- `test_run_completion_graph_stream_yields_sse_events_and_terminal_completion`：验证 graph 输出标准 SSE 事件，先创建 completion，再输出 source index、模型/工具事件，最后以 `completion.completed` 收口，并保持 seq 连续递增；`source_selectors` 同时包含 document/section header 和可读 block 的原文 DOM id。
- `test_run_completion_graph_stream_flushes_after_each_tool_call`：验证 graph 会在每次工具调用前后持续 flush 事件，而不是等整轮 QA 完成后批量返回。
