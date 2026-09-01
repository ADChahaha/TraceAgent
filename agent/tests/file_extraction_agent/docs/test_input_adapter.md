# test_input_adapter.py

这份测试覆盖 QA completion 输入适配层。入口不再接收 `task_spec`，而是接收
backend 持久化后的 `completion_id + documents + append-only messages`，并把
HTML documents 落盘成真实文件树（`materialize_tree`）。

实现链路：

```text
completion_id + documents + messages
  -> 校验 completion_id 非空
  -> 校验至少一个 document 且每个 document 有 filename/html
  -> 校验至少一个历史/当前 message，支持 OpenAI 风格 tool history
  -> materialize_tree(documents, workspace_root/<completion_id>) 落盘真实文件树
  -> 返回 DocumentQaCompletionInput(document=DocumentFileTree)
```

说明：workspace 根默认取 `FILE_EXTRACTION_AGENT_WORKSPACE_ROOT` 环境变量
（默认 `agent/data/qa_workspace`），每 completion 一个子目录，completion
结束后清理。测试里通过 `workspace_root=tmp_path` 隔离。

## 测试函数

- `test_build_completion_input_accepts_documents_and_append_only_messages`：验证输入适配层会保留 completion id、文档和消息，并把 document 落盘到 `workspace_root/<completion_id>`；图输入上不再存在 memory。
- `test_build_completion_input_rejects_memory_argument`：验证内部输入适配入口不再接收 `memory` 参数。
- `test_build_completion_input_rejects_missing_documents_or_messages`：验证缺少文档或消息时会拒绝。
- `test_build_completion_input_rejects_document_without_filename_or_html`：验证 document 缺少文件名或 HTML 正文时会拒绝。
- `test_build_completion_input_requires_completion_id`：验证 completion id 不能为空。
