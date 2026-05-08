# test_broad_new.py

这份测试覆盖 broad planning 阶段的 prompt 构造、no-plan 实验入口和结构化计划解析兼容性。No-plan 模式下 `run_broad_planner` 不再调用 broad 模型，而是直接写入空 `BroadPlan`，让 resolution 只依赖 task fields 与 document outline 自主找证据。

实现链路：

```text
task_spec + document.tree + 完整 HTML
  -> build_broad_messages 生成英文 broad system/user prompt
  -> prompt 说明 broad plan 是导航计划、不能写具体答案值，并说明 resolution 可用工具、表格查询策略和“尽量使用文档语言写计划”
  -> run_broad_planner 在 no-plan 模式下跳过模型调用并返回空 BroadPlan
  -> parse_broad_plan_tool_call 保留旧结构化计划解析兼容性
```

## 测试函数

- `test_build_broad_messages_includes_task_and_tree`：确认 broad prompt 包含任务字段、文档树、完整 HTML、英文 resolution 工具清单（包括 `search_elements` 候选定位工具）、表格先读列再查 SQL 的策略、大表裸 `SELECT *` 禁令、`LIMIT 50` 分页保底、禁止预填最终答案，并明确 plan 是导航计划而不是答案草稿，不能写具体抽取值或规范化字段值；任务相关类别只能来自 `task_spec` 的字段名和描述，不能在 broad prompt 代码里内置具体任务字段语义；规划表格字段时要让 resolution 在 `set_field.reason` 解释 `query_audit.summary`，并要求计划文本尽量使用文档语言。
- `test_run_broad_planner_skips_model_and_returns_empty_plan`：确认 no-plan 模式下 broad 阶段不会绑定工具或调用模型，而是直接返回 `summary="No broad plan"`、空 `plan` 和空 `risks`。
- `test_parse_broad_plan_tool_call_reads_function_arguments`：确认能从 function/tool call 参数中解析 broad plan。
- `test_parse_broad_plan_keeps_string_list_values_as_single_items`：确认模型把字符串当作 plan/risks 返回时会被归一化为单项列表。
