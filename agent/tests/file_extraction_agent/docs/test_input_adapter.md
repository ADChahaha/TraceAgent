# test_input_adapter.py

这份测试覆盖 QA completion 输入适配层。入口不再接收 `task_spec`，而是接收 backend 持久化后的 `completion_id + documents + append-only messages`，并构建本轮 completion 使用的虚拟文档树。

实现链路：

```text
completion_id + documents + messages
  -> 校验 completion_id 非空
  -> 校验至少一个 document 且每个 document 有 filename/html
  -> 校验至少一个历史/当前 message，支持 OpenAI 风格 tool history
  -> 构建 HtmlDocument virtual tree
  -> 返回 DocumentQaCompletionInput
```

## 测试函数

- `test_build_completion_input_accepts_documents_and_append_only_messages`：验证输入适配层会保留 completion id、文档和消息，并构建可读 virtual tree；图输入上不再存在 memory。
- `test_build_completion_input_rejects_memory_argument`：验证内部输入适配入口不再接收 `memory` 参数。
- `test_build_completion_input_rejects_missing_documents_or_messages`：验证缺少文档或消息时会拒绝。
- `test_build_completion_input_rejects_document_without_filename_or_html`：验证 document 缺少文件名或 HTML 正文时会拒绝。
- `test_build_completion_input_requires_completion_id`：验证 completion id 不能为空。
