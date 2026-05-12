# test_graph.py

这份测试覆盖 HTML 抽取图的顶层编排。它不连接真实模型，而是用 fake resolution model 验证 no-plan 流程、resolution 阶段、结果映射和失败 trace 的边界行为。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_input 归一化输入
  -> run_extraction_graph 直接运行 resolution
  -> resolution fake model 按 read_blocks(indexes)/query_table/set_field/finish 或 read_blocks/preview_inline_evidence/set_field/finish 顺序调用工具
  -> map_state_to_result 把 field_states 和 actions 写入 ExtractionResult
```

## 测试函数

- `test_map_state_to_result_returns_completed_payload`：确认已解析字段会进入 completed 结果，并且 trace 不再包含 broad plan 字段。
- `test_build_failed_result_preserves_trace`：确认任一阶段抛异常时会返回 failed 结果，并在 trace 中保留失败阶段。
- `test_run_extraction_graph_runs_resolution_without_broad_plan_trace`：确认顶层流程不会生成 broad plan trace，然后按 no-plan resolution 工具协议读取表格、写字段并 finish。
- `test_run_extraction_graph_runs_new_read_tools_without_document_scan_model`：确认只用新读取工具和 inline 证据预览也能完成字段写入。
