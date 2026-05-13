# test_input_adapter.py

这份测试覆盖 `file_extraction_agent` 的新输入适配层。入口不再接收单个聚合 `html`，而是接收多个 `documents`，每个 document 必须包含 `filename` 和 `html`。

实现链路：

```text
documents + task_spec + run_options
  -> 校验 documents 非空
  -> 校验每个 document 有 filename 和非空 html
  -> 归一化 TaskSpec / RunOptions
  -> build_html_document(documents)
  -> HtmlExtractionInput(documents, task_spec, document, run_options)
```

## 测试函数

- `test_build_graph_input_accepts_documents_with_filename_and_html`：确认多文档输入会被解析成内部 document 对象和虚拟路径索引。
- `test_build_graph_input_rejects_missing_documents`：确认空 documents 会被拒绝。
- `test_build_graph_input_rejects_document_without_filename_or_html`：确认单个 document 缺少 filename 或 html 会返回清晰错误。
- `test_build_graph_input_rejects_missing_task_spec`：确认 task spec 仍是必需输入。
- `test_build_graph_input_rejects_empty_fields`：确认 task spec fields 不能为空。
