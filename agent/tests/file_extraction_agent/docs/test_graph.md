# test_graph.py

这份测试覆盖新抽取图的流式编排和最终结果映射。图执行器不再返回旧的裸字段值，而是输出 NDJSON 事件流，最后以字段对象数组完成结果。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> fake model 依次调用 tree/read/anchors/bind_evidence/review_field/write_field/submit_result
  -> 工具层写入 state.events
  -> run_extraction_graph_stream 逐条 yield NDJSON
  -> map_state_to_result 生成 fields 数组、selector 反查文本和 trace
```

## 测试函数

- `test_run_extraction_graph_stream_yields_ndjson_events_and_final_result`：确认流式图会按工具调用顺序输出 NDJSON 事件，事件 `seq` 连续递增，最后一条是 `result_completed`，字段结果会把 `write_field(final_evidence=...)` 保留的最终 selector 和 `evidence_texts` 带入最终结果，方便回放和评测。
- `test_run_extraction_graph_stream_flushes_events_after_each_tool_call`：确认 graph stream 会在每次工具调用后立即产出事件，而不是等整轮 resolution 结束后批量返回。
- `test_map_state_to_result_returns_new_field_result_shape`：确认最终结果使用 `fields[]` 字段对象结构，保留证据 selector 的反查文本，并且 trace 不再包含 soft plan。
