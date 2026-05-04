# test_graph.py

这份测试覆盖 HTML 抽取图的顶层编排。它不连接真实模型，而是用 fake broad model 和 fake resolution model 验证 broad 阶段、resolution 阶段、结果映射和失败 trace 的边界行为。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_input 归一化输入
  -> run_extraction_graph 先执行 broad planner
  -> resolution fake model 按 update_plan/read/table/set_field/finish 顺序调用工具
  -> map_state_to_result 把 field_states、broad_plan、actions 写入 ExtractionResult
```

## 测试函数

- `test_map_state_to_result_returns_completed_payload`：确认已解析字段会进入 completed 结果，并且 trace 保留 broad plan。
- `test_build_failed_result_preserves_trace`：确认任一阶段抛异常时会返回 failed 结果，并在 trace 中保留失败阶段。
- `test_run_extraction_graph_executes_broad_then_resolution`：确认顶层流程会先执行 broad，再按 resolution 工具协议顺序推进 plan、读取表格、写字段并 finish。
