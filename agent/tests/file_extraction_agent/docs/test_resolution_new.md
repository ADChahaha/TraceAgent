# test_resolution_new.py

这份测试覆盖 resolution agent 的 prompt、文档 outline 格式和 LangGraph 工具循环。重点是确认模型看到紧凑、可定位的文档结构，并且按“先定位、再精读、证据足够立即写字段、最后 finish”的链路执行。

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
- `test_resolution_messages_embed_compact_document_outline`：确认 resolution prompt 包含 compact outline、字段一次性定案规则、reason 面向用户和尽量使用文档语言的约束、replay 同步约束、`update_plan` 局部工作单元约束、允许少量相邻字段扩展但避免大范围漂移的约束、切换 plan 后重新读取或 preview 证据的约束、`record_note` 字段笔记要求、section/同层 block 读取策略、inline/table row/list item 证据粒度要求，并把具体工具参数与读取行为交给 LangGraph 绑定的 tool docstring 注入；同时确认不再内嵌 `query_audit` 相关提示，也不把 plan 粒度写成固定数字上限。
- `test_format_document_outline_prioritizes_index_pages`：确认疑似目录页会被放进 `index-pages`，模型应先用它定位主章节。
- `test_resolution_graph_nudges_model_when_it_stops_before_finish`：确认字段已写但模型停在普通文本时，会收到继续调用工具的提醒并最终触发 `finish`。
- `test_resolution_nudge_counts_new_read_tools_as_observed_evidence`：确认 `read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence` 等读取或证据细化动作会触发“停止广泛浏览、优先 set_field”的 nudge。
- `test_resolution_graph_exposes_plan_and_new_read_tools`：确认 resolution 图暴露 `update_plan`、`overview`、`read_section`、`read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence`、`set_field` 和 `finish`。
