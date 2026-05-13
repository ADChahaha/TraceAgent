# test_file_extraction_agent_route.py

这份测试覆盖 `file_extraction_agent` 的 stream-first HTTP 出口。route 层接收 `documents + task_spec`，调用业务层 `extract_stream(...)`，并用 NDJSON 返回真实工具事件。

实现链路：

```text
HTTP POST /v1/file-extraction-agent/extract/stream
  -> route 层解析 documents、task_spec、run_options、model_config
  -> 调用 service.file_extraction_agent.processor.extract_stream(...)
  -> StreamingResponse(application/x-ndjson)
```

## 测试函数

- `test_file_extraction_agent_stream_route_calls_stream_extractor`：确认 stream route 会把 documents 和 task_spec 传给业务入口，并返回 NDJSON。
- `test_file_extraction_agent_stream_route_passes_run_options`：确认 `run_options` 会解析成 `RunOptions` 后传给业务入口。
- `test_file_extraction_agent_stream_route_passes_resolution_model_overrides`：确认 HTTP 模型覆盖参数会传入业务入口。
- `test_file_extraction_agent_stream_route_rejects_legacy_html_payload`：确认旧 `html` payload 不再被接受。
- `test_file_extraction_agent_stream_route_rejects_unknown_payload_fields`：确认 route 层拒绝未声明字段。
