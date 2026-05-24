# test_file_extraction_agent_route.py

这份测试覆盖 `document-qa chat/completions` 的 HTTP 出口。route 层接收 backend 传来的 `completion_id + documents + append-only messages`，调用业务层 `create_completion_stream(...)`，并用 SSE 返回 QA agent 的过程事件。

实现链路：

```text
HTTP POST /v1/document-qa/chat/completions
  -> route 层解析 documents、messages、run_options、model_config
  -> 调用 service.file_extraction_agent.processor.create_completion_stream(...)
  -> StreamingResponse(text/event-stream)

HTTP POST /v1/document-qa/chat/completions/{completion_id}/cancel
  -> route 层调用 service.file_extraction_agent.processor.cancel_completion(...)
  -> 返回 completion 当前取消状态
```

## 测试函数

- `test_document_qa_chat_completion_route_calls_completion_stream`：确认 chat completion route 会把 completion id、documents 和 messages 传给业务入口，并返回 SSE；不会再传 memory。
- `test_document_qa_chat_completion_route_rejects_memory_field`：确认 HTTP 入口拒绝 `memory` 字段，避免重新引入会破坏 append-only prompt cache 的摘要通路。
- `test_document_qa_chat_completion_route_passes_run_options`：确认 `run_options` 会解析成 `RunOptions` 后传给业务入口。
- `test_document_qa_chat_completion_route_passes_model_overrides`：确认 HTTP 模型覆盖参数会把 `model` 和 `api_transport` 传入业务入口。
- `test_document_qa_completion_cancel_route_calls_processor`：确认 cancel route 会把 completion id 交给业务层并返回取消状态。
- `test_legacy_file_extraction_route_is_removed`：确认旧字段抽取 route 不再暴露。
- `test_document_qa_chat_completion_rejects_task_spec_payload`：确认新的 QA completion route 拒绝旧 `task_spec` payload。
- `test_document_qa_chat_completion_rejects_empty_documents_before_streaming`：确认 documents 为空这类业务入参错误会在创建 SSE 前返回 422，而不是先返回 200 再在流式迭代时失败。
