# test_broad_new.py

这份测试覆盖 broad planning 阶段的 prompt 构造、工具绑定和结构化计划解析。Broad 只能调用 `return_broad_plan`，但 prompt 会告诉它 resolution 后续可用哪些工具，方便它写出可执行计划。

实现链路：

```text
task_spec + document.tree + 完整 HTML
  -> build_broad_messages 生成 broad system/user prompt
  -> prompt 说明 resolution 可用工具和表格查询策略
  -> run_broad_planner 只绑定 return_broad_plan
  -> parse_broad_plan_tool_call 解析 summary/plan/risks
```

## 测试函数

- `test_build_broad_messages_includes_task_and_tree`：确认 broad prompt 包含任务字段、文档树、完整 HTML、resolution 工具清单、表格先读列再查 SQL 的策略、大表裸 `SELECT *` 禁令、`LIMIT 50` 分页保底，以及规划表格字段时要让 resolution 在 `set_field.reason` 解释 `query_audit.summary`。
- `test_run_broad_planner_binds_only_plan_output_function`：确认 broad 阶段只绑定 `return_broad_plan`，不会把 resolution 的读文档工具暴露给 broad 模型。
- `test_parse_broad_plan_tool_call_reads_function_arguments`：确认能从 function/tool call 参数中解析 broad plan。
- `test_parse_broad_plan_keeps_string_list_values_as_single_items`：确认模型把字符串当作 plan/risks 返回时会被归一化为单项列表。
