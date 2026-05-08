# test_graph.py

这份测试覆盖 HTML 抽取图的顶层编排。它不连接真实模型，而是用 fake broad model 和 fake resolution model 验证 no-plan broad 占位、隔离 scoped scan 模型传递、resolution 阶段、结果映射和失败 trace 的边界行为。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_input 归一化输入
  -> run_extraction_graph 写入空 broad plan 占位，把 broad_model 挂到 document_scan_model
  -> resolution fake model 按 read/table/set_field/finish 或 scan_document(scope_id)/set_field/finish 顺序调用工具
  -> map_state_to_result 把 field_states、broad_plan、actions 写入 ExtractionResult
```

## 测试函数

- `test_map_state_to_result_returns_completed_payload`：确认已解析字段会进入 completed 结果，并且 trace 保留 broad plan。
- `test_build_failed_result_preserves_trace`：确认任一阶段抛异常时会返回 failed 结果，并在 trace 中保留失败阶段。
- `test_run_extraction_graph_skips_broad_plan_then_runs_resolution`：确认顶层流程不会调用 broad 模型，会写入空 broad plan 占位，然后按 no-plan resolution 工具协议读取表格、写字段并 finish。
- `test_run_extraction_graph_uses_broad_model_only_as_document_scan_model`：确认 broad_model 不参与 broad plan，但会作为 `scan_document(scope_id, ...)` 的隔离 reader 被 resolution 显式调用；该 reader 不绑定工具，返回的候选证据进入 trace action。
