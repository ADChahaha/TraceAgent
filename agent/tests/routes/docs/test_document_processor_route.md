# test_document_processor_route.py

这份测试文档对应 `tests/routes/test_document_processor_route.py`，覆盖 `service.document_processor` 的 HTTP 最终出口。

## 实现链路

```text
HTTP multipart 上传 file + file_type
  -> FastAPI app 挂载 document processor router
  -> route 层把 UploadFile 包装成业务层可读取的 file-like 对象
  -> 调用 service.document_processor.processor.process(file_obj, file_type)
  -> 把 ProcessResult 映射成 JSON 响应
```

## 测试函数

- `test_document_processor_process_route_calls_business_processor`
  - 验证 `/v1/document-processor/process` 会把上传文件和显式 `file_type` 传给业务入口。
  - 验证 route 层不会重新定义业务结果，只把 `ProcessResult` 的 markdown、blocks、meta_info 和 warnings 转成 HTTP 响应。
