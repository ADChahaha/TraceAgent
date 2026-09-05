# test_file_extraction_agent_route.py

`test_document_qa_chat_completion_route_calls_completion_manager` 检查资源路径传给 manager，且不传递 task_id。

这份测试覆盖 `document-qa chat/completions` 的 HTTP 出口。route 层接收 backend 传来的 `completion_id + resource_path + append-only messages`，调用业务层 `completion_manager.create(...)`，并用 SSE 返回 QA agent 的过程事件。

实现链路：

```text
HTTP POST /v1/document-qa/chat/completions
  -> route 层解析 resource_path、messages、run_options、model_config
  -> 调用 service.file_extraction_agent.manager.completion_manager.create(...)
  -> StreamingResponse(text/event-stream)

HTTP POST /v1/document-qa/chat/completions/{completion_id}/cancel
  -> route 层调用 service.file_extraction_agent.manager.completion_manager.terminate(...)
  -> 返回 completion 当前取消状态
```

## 测试函数

- `test_document_qa_chat_completion_route_calls_completion_manager`：确认 chat completion route 会把 completion id、resource_path 和 messages 传给业务入口，并返回 SSE；不会再传 memory。
- `test_document_qa_chat_completion_route_rejects_memory_field`：确认 HTTP 入口拒绝 `memory` 字段，避免重新引入会破坏 append-only prompt cache 的摘要通路。
- `test_document_qa_chat_completion_route_passes_run_options`：确认 `run_options` 会解析成 `RunOptions` 后传给业务入口。
- `test_document_qa_chat_completion_route_passes_model_overrides`：确认 HTTP 模型覆盖参数会被组装成一个 `ModelConfig` 对象传入业务入口（`base_url`、`api_key`、`model_name`、`api_transport`、`temperature`、`top_p`、`top_k`）。
- `test_document_qa_completion_cancel_route_calls_processor`：确认 cancel route 会把 completion id 交给业务层并返回取消状态。
- `test_legacy_file_extraction_route_is_removed`：确认旧字段抽取 route 不再暴露。
- `test_document_qa_chat_completion_rejects_task_spec_payload`：确认新的 QA completion route 拒绝旧 `task_spec` payload。
- `test_document_qa_chat_completion_rejects_legacy_documents_before_streaming`：确认 旧 documents 请求会在创建 SSE 前返回 422，而不是先返回 200 再在流式迭代时失败。

请求改为 resource_path；不再向 manager 传 documents 或 task_id，历史消息与模型配置测试保留。
`test_document_qa_completion_cancel_route_calls_manager`：取消路由按 completion ID 转发 manager，保留取消响应。

测试调用与替身模型名称同步采用 qa 命名，验证行为保持原契约。

路由测试替换模块顶部直接导入的 completion_manager 引用，验证创建、参数转发及取消不再依赖运行时动态导入。
