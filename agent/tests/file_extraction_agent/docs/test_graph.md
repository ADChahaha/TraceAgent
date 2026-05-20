# test_graph.py

这份测试覆盖新抽取图的流式编排和最终结果映射。图执行器不再返回旧的裸字段值，而是输出 NDJSON 事件流，最后以字段对象数组完成结果。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> run_extraction_graph_stream 先输出 source_indexed(document_tree + source_selectors)，供前端运行中打开原文和高亮
  -> fake model 使用 tree 输出的新式 evidence:// locator（例如 `evidence://0001.0001.0001`）和可选 content 依次调用 tree/read/add_candidate_evidence/review_evidences/write_field/submit_result
  -> fake loop 把 fake model 的 content 写入 state.current_model_content，工具参数本身不携带 reason
  -> 工具层写入 state.events
  -> run_extraction_graph_stream 逐条 yield NDJSON
  -> map_state_to_result 生成带 `field_name` 的 fields 数组、selector 反查文本和 trace
```

## 测试函数

- `test_run_extraction_graph_stream_yields_ndjson_events_and_final_result`：确认流式图先输出 `source_indexed`，随后按工具调用顺序输出 NDJSON 事件，事件 `seq` 连续递增，最后一条是 `result_completed`；fake model 面向工具传 `evidence://` block/inline links，工具内部会把 `write_field(final_evidence=...)` 转回 canonical `path_id` selector、`evidence_texts` 和来自 fake model content 的兼容说明带入最终结果，并且最终字段对象对 backend 输出 `field_name`。
- `test_run_extraction_graph_stream_flushes_events_after_each_tool_call`：确认 graph stream 会先立即产出 `source_indexed`，并在每次工具调用后继续产出事件，而不是等整轮 resolution 结束后批量返回。
- `test_map_state_to_result_returns_new_field_result_shape`：确认最终结果使用带 `field_name` 的 `fields[]` 字段对象结构，保留证据 selector 的反查文本，并且 trace 不再包含 soft plan。
