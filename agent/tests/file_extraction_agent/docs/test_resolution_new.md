# test_resolution_new.py

这份测试覆盖 resolution agent 的 prompt、文档 outline 格式和 LangGraph 工具循环。重点是确认模型看到的是紧凑、可定位的文档结构，并且在 no-plan 实验模式下直接依据 task fields 与 document outline 自主选择搜索、按 scope id 隔离扫描和读取工具，不再等待或调用 broad plan / `update_plan`。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_state 构造 resolution state
  -> build_resolution_messages 生成英文 system/human prompt
  -> format_document_outline 输出紧凑 outline
  -> build_resolution_graph 绑定工具并执行 fake model
  -> 校验 prompt 约束、outline 内容、nudge 行为和工具暴露顺序
```

## 测试函数

- `test_format_document_outline_returns_compact_text_not_raw_json`：确认 outline 是模型友好的 XML-like 文本，包含章节和表格引用，不暴露原始 Python dict 或正文噪声。
- `test_resolution_messages_embed_compact_document_outline`：确认 resolution prompt 包含 compact outline、字段写入规则、reason 尽量使用文档语言的约束、明确没有 broad plan 且不要调用 `update_plan`、`search_elements` 直接返回可读 HTML 且 evidence id 可直接写入字段的策略、`scan_document(scope_id, query, reason, limit)` 必须先选定 scope id，只扫描该 id 下完整内容并只返回候选证据、`read_section` 因章节过长会自动使用同一 section id 触发隔离 reader 并返回候选证据、章节读取策略、SQL 列名双引号要求，以及 query audit few-shot：空白筛选列必须结合表头、表注、相邻列和字段目标判断，不能只因为 WHERE 未选中就说正常，也不要求模型按非空数量分布下结论。
- `test_format_document_outline_prioritizes_index_pages`：确认疑似目录页会被放进 `index-pages`，模型应先用它定位主章节。
- `test_resolution_graph_nudges_model_when_it_stops_before_finish`：确认模型在字段已写但没调用 `finish` 时，会收到英文继续调用工具的提醒并最终触发 `finish`。
- `test_resolution_nudge_counts_search_results_as_observed_evidence`：确认连续搜索和读取都被视为已观察证据，模型多轮查找后会被提醒停止浏览并优先 `set_field`。
- `test_resolution_graph_does_not_expose_update_plan_tool`：确认 no-plan 模式不再向 resolution 模型暴露 `update_plan`，工具列表从 `search_elements` 开始，并包含按 scope id 隔离扫描用的 `scan_document`。
