# test_broad_new.py

这份测试覆盖 broad planning 阶段的 prompt 构造、默认导航计划和结构化计划解析兼容性。当前实现不会在 broad 阶段调用模型，而是给 resolution 留一个默认导航计划和兼容 trace。

实现链路：

```text
task_spec + document.tree + 完整 HTML
  -> build_broad_messages 生成英文 broad system/user prompt
  -> prompt 说明 broad plan 是导航计划，不能写具体答案值
  -> prompt 说明 resolution 可用工具、顶层 list/table 直接入口和表格查询策略
  -> run_broad_planner 跳过模型调用并写入默认 BroadPlan
  -> parse_broad_plan_tool_call 保留旧结构化计划解析兼容性
```

## 测试函数

- `test_build_broad_messages_includes_task_and_tree`：确认 broad prompt 包含任务字段、文档树、完整 HTML、resolution 工具名清单（包含离散读取 `read_blocks` 和连续读取 `read_block_range`），并说明精确工具参数来自 resolution 阶段绑定的 tool docstring；同时覆盖大表 `SELECT *` 限制、`query_table` 的 `summary/table_audit` 说明、禁止预填最终答案，以及不再包含任务特化示例。
- `test_run_broad_planner_skips_model_and_returns_default_plan`：确认 broad 阶段不会绑定工具或调用模型，而是返回默认三步导航计划并写入 `state.broad_plan`。
- `test_parse_broad_plan_tool_call_reads_function_arguments`：确认能从 function/tool call 参数中解析 broad plan。
- `test_parse_broad_plan_keeps_string_list_values_as_single_items`：确认模型把字符串当作 plan/risks 返回时会被归一化为单项列表。
