# test_resolution_new.py

这份测试覆盖 resolution agent 的 prompt、文档 outline 格式和 LangGraph 工具循环。重点是确认模型看到紧凑、可定位的文档结构，并且按“先定位、再精读、`complete_stage(fields=[...])` 批量写可靠字段、最后 finish”的链路执行。

实现链路：

```text
测试 HTML + task_spec
  -> build_graph_state 构造 resolution state
  -> build_resolution_messages 生成英文 system/human prompt
  -> format_document_outline 输出 XML-like 紧凑 outline
  -> build_resolution_graph 绑定工具并执行 fake model
  -> 校验 prompt 约束、outline 内容、nudge 行为和工具暴露顺序
```

## 测试函数

- `test_format_document_outline_returns_compact_text_not_raw_json`：确认 outline 是模型友好的 XML-like 文本，包含章节和表格引用，不暴露 Python dict 或正文噪声。
- `test_resolution_messages_embed_compact_document_outline`：确认 resolution prompt 包含 compact outline、字段通过 `complete_stage.fields[]` 定案、Reading Stages append-only 约束、stage 是相关证据到字段写入单元的粒度约束、相关字段可以同 stage、不相关字段必须换 stage、单活动 stage 约束、`start_stage` 后必须先追加阅读类 progress 才能读取、`complete_stage` 只提交当前已可靠字段且失败后继续同 stage 读取、`compare/verify_absence` 的通用触发规则、候选证据需要逐字段记录、已有字段候选证据后应优先收口而不是继续扩展 stage、字段级 rationale 要求；同时确认 section/同层 block 读取策略、inline/table row/list item 证据粒度要求会保留，具体工具参数、读取行为和读取类工具必填 `reason` 交给 LangGraph 绑定的 tool docstring/schema 注入，且不引入 `hypothesis`、polarity 拆分规则、`query_audit`、旧计划工具或单独 `evidence_note_ids`。
- `test_resolution_task_fields_include_enum_variants_for_tagged_values`：确认 resolution prompt 的字段清单会把 enum variants 展开为 `name:type`，并提示模型用 `{"variant": "name", "value": ...}` 这种 tagged object 写 enum 值。
- `test_format_document_outline_prioritizes_index_pages`：确认疑似目录页会被放进 `index-pages`，模型应先用它定位主章节。
- `test_resolution_graph_nudges_model_when_it_stops_before_finish`：确认字段已写但模型停在普通文本时，会收到继续调用工具的提醒并最终触发带显式确认参数的 `finish`。
- `test_resolution_nudge_counts_new_read_tools_as_observed_evidence`：确认 `read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence` 等读取或证据细化动作会触发“停止广泛浏览、证据足够就用 `complete_stage` 写当前 stage 的可靠字段”的 nudge，并提醒已有字段候选证据时应先写该字段，不继续浏览无关内容。
- `test_resolution_nudge_keeps_missing_fields_from_becoming_plan_items`：确认缺失字段提醒只用于识别未解决证据需求，不鼓励模型把字段列表改写成 stage，并提示 `complete_stage` 只能在已有阅读进展且证据足够后使用，也不要积累大量字段候选证据到最后统一写。
- `test_resolution_graph_exposes_plan_reading_stage_and_read_tools`：确认 resolution 图暴露 Reading Stages 工具、`complete_stage`、`overview`、`read_section`、`read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence` 和 `finish`，不再暴露旧计划工具或单字段写入工具。
- `test_resolution_tools_expose_reason_only_for_read_tools`：确认只有 `overview/read_section/read_blocks/read_block_range/read_list/query_table/preview_inline_evidence` 这些读取相关工具向模型暴露必填 `reason` 参数，用来说明为什么要读；stage、候选证据、字段写入和 finish 仍不暴露旧的通用 reason 参数。
