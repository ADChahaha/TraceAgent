# test_graph.py

这份测试覆盖 HTML 抽取图的顶层编排。它不连接真实模型，而是用 fake resolution model 验证 resolution 阶段、软计划 trace、结果映射和失败 trace 的边界行为。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_input 归一化输入
  -> run_extraction_graph 直接构造 GraphState 并进入 resolution
  -> resolution fake model 按 update_soft_plan/read_blocks/query_table/set_field/update_soft_plan/finish 或 read_blocks/preview_inline_evidence/set_field/finish 顺序调用工具
  -> map_state_to_result 把 soft_plan、plan_statuses、notes、field_states、actions 写入 ExtractionResult.trace
```

## 测试函数

- `test_map_state_to_result_returns_completed_payload`：确认已解析字段会进入 completed 结果，trace 不再包含 broad plan，并保留 soft plan 和 `record_note` 写入的 notes。
- `test_build_failed_result_preserves_trace`：确认 resolution 抛异常时会返回 failed 结果，并在 trace 中保留失败阶段。
- `test_run_extraction_graph_runs_resolution_with_soft_plan`：确认顶层流程直接进入 resolution，软计划写入 trace，然后按工具协议读取表格、写字段、把 soft plan 全部更新为 completed，并最终 finish。
- `test_run_extraction_graph_runs_new_read_tools_without_scan_model`：确认只用读取工具和 inline 证据预览也能完成字段写入，不依赖隔离 scan 模型。
