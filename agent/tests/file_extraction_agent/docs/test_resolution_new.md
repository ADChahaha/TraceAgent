# test_resolution_new.py

这份测试覆盖 resolution agent 的 prompt、文档 outline 格式和 LangGraph 工具循环。重点是确认模型看到的是紧凑、可定位的文档结构，并且被明确要求按 broad plan 顺序调用工具和写字段。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_state 构造 resolution state
  -> build_resolution_messages 生成 system/human prompt
  -> format_document_outline 输出紧凑 outline
  -> build_resolution_graph 绑定工具并执行 fake model
  -> 校验 prompt 约束、outline 内容、nudge 行为和工具暴露顺序
```

## 测试函数

- `test_format_document_outline_returns_compact_text_not_raw_json`：确认 outline 是模型友好的 XML-like 文本，包含章节和表格引用，不暴露原始 Python dict 或正文噪声。
- `test_resolution_messages_embed_compact_document_outline`：确认 resolution prompt 包含 compact outline、字段写入规则、中文 replay reason 规则、按最早未完成 broad plan 顺序推进的约束、章节读取策略、SQL 列名双引号要求，以及 query audit few-shot：空白筛选列必须结合表头、表注、相邻列和字段目标判断，不能只因为 WHERE 未选中就说正常。
- `test_format_document_outline_prioritizes_index_pages`：确认疑似目录页会被放进 `index-pages`，模型应先用它定位主章节。
- `test_resolution_graph_nudges_model_when_it_stops_before_finish`：确认模型在字段已写但没调用 `finish` 时，会收到继续调用工具的提醒并最终触发 `finish`。
- `test_resolution_graph_exposes_update_plan_tool`：确认 `update_plan` 是 resolution 工具列表里的第一个工具，方便模型先同步 replay plan。
