# `test_document_processor_route.py`

这份测试文档对应 `tests/routes/test_document_processor_route.py`，覆盖 PDF 转 HTML 的 HTTP 出口。

## 实现链路

```text
HTTP 请求
  -> FastAPI app 挂载 document processor router
  -> capabilities 返回 PDF-only 能力声明和 docling 缓存目录
  -> multipart 上传 file + file_type
  -> UploadFileProxy 包装成业务层可读取 file-like 对象
  -> service.document_processor.processor.process(file_obj, file_type)
  -> ProcessResult(filename, html)
  -> JSON 响应
```

## 测试函数

`test_document_processor_capabilities_route_reports_pdf_only_processor`

- 验证 `/v1/ocr/capabilities` 能返回 200。
- 验证能力声明只包含 `pdf`。
- 验证返回 docling 模型目录状态。

`test_document_processor_route_uses_public_processor_exception_contract`

- 验证 route 不引用 `service.document_processor.impl`。
- 验证 route 只依赖公开业务入口暴露的异常契约。

`test_document_processor_process_route_calls_business_processor`

- 用 fake business `process(...)` 替代真实 docling。
- 验证 route 会把上传文件和显式 `file_type` 交给业务入口。
- 验证 HTTP 响应只包含 `filename/html`。
