# test_resolution_new.py

这份测试覆盖 resolution agent 的 prompt、文档 outline 格式和 LangGraph 工具循环。重点是确认模型看到紧凑、可定位的文档结构，并且按“先定位、再精读、进入 conclude、写字段、最后 finish”的链路执行。

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
- `test_resolution_messages_embed_compact_document_outline`：确认 resolution prompt 包含 compact outline、字段一次性定案规则、Reading Stages append-only 约束、stage 是相关证据到字段写入单元的粒度约束、单活动 stage 约束、`start_stage` 后必须先追加阅读类 progress 才能读取、`conclude` 不能作为首个 progress、进入 `conclude` 后才能 `review_stage_evidence/set_field` 的门控、`compare/verify_absence` 的通用触发规则、候选证据 note 与字段共享 `evidence_ids`、字段级 rationale 要求；同时确认 section/同层 block 读取策略、inline/table row/list item 证据粒度要求会保留，具体工具参数与读取行为交给 LangGraph 绑定的 tool docstring 注入，且不再内嵌 `query_audit`、旧计划工具、单独 `evidence_note_ids` 或强制 `reason` 参数相关提示。
- `test_resolution_task_fields_include_enum_variants_for_tagged_values`：确认 resolution prompt 的字段清单会把 enum variants 展开为 `name:type`，并提示模型用 `{"variant": "name", "value": ...}` 这种 tagged object 写 enum 值。
- `test_format_document_outline_prioritizes_index_pages`：确认疑似目录页会被放进 `index-pages`，模型应先用它定位主章节。
- `test_resolution_graph_nudges_model_when_it_stops_before_finish`：确认字段已写但模型停在普通文本时，会收到继续调用工具的提醒并最终触发 `finish`。
- `test_resolution_nudge_counts_new_read_tools_as_observed_evidence`：确认 `read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence` 等读取或证据细化动作会触发“停止广泛浏览、证据足够先 conclude 再 set_field；证据不足则不要写也不要直接读，先在同一 stage 追加 investigate 撤回写字段检查点”的 nudge，并提醒新开 stage 后先追加阅读类 progress 再读取。
- `test_resolution_nudge_keeps_missing_fields_from_becoming_plan_items`：确认缺失字段提醒只用于识别未解决证据需求，不鼓励模型把字段列表改写成 stage，并提示 `conclude` 只能在已有阅读进展且证据足够后使用。
- `test_resolution_graph_exposes_plan_reading_stage_and_read_tools`：确认 resolution 图暴露 Reading Stages 工具、`overview`、`read_section`、`read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence`、`set_field` 和 `finish`，不再暴露旧计划工具。
- `test_resolution_tools_do_not_expose_reason_argument`：确认所有暴露给模型的 resolution tools schema 都不包含 `reason` 参数，避免 no-reason ablation run 继续让模型在 tool call 中填写原因字段。
