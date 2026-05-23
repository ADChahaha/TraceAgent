# test_agent_client.py

这份测试覆盖 backend 到 agent service 的 HTTP client 分流。backend 不 import
agent 内部模块，只根据已经校验出的 `file_type` 选择 agent HTTP endpoint。

## 实现链路

```text
QaTaskService._process_document(...)
  -> AgentClient.process_document(file_bytes, filename, content_type, file_type)
  -> file_type=pdf  选择 /v1/document-processor/process
  -> file_type=docx 选择 /v1/document-processor/docx/process
  -> multipart file + form file_type 传给 agent
  -> 返回 agent JSON
```

## 测试函数

- `test_process_document_routes_pdf_to_existing_pdf_endpoint`：验证 PDF 保持走现有
  document processor endpoint，并继续携带 multipart file 和 `file_type=pdf`。
- `test_process_document_routes_docx_to_docx_endpoint`：验证 DOCX 走新增的专用
  endpoint，不混入 PDF endpoint。
- `test_process_document_rejects_unknown_file_type_before_agent_call`：验证未知类型在
  backend client 侧直接拒绝，避免误打 agent 的 PDF 或 DOCX endpoint。
