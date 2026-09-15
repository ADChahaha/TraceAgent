# 文档资源 gRPC 测试

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

独立 document service 的真实 DOCX 上传 → 真实 HTML 解析与文档树生成 → 替身 embedding → 发布到 storage 服务（返回资源定位数组）。本文件只验证 document service 的 RPC、资源契约及错误码；agent 的消费链路见 `test_agent_resource_integration.py`。

- `test_prepare_real_docx_publishes_complete_resource`：真实多文档上传发布单个 `documents.zip` 和独立的 manifest/index/vectors/raw 对象，不再内联返回 HTML，也不再在桶里散落 `documents/` 前缀对象。
- `test_protocol_prepare_response_drops_documents_payload`：`PrepareResourcesResponse` 只保留 `resource_path`，`documents` 字段与 `Document` 消息已从协议移除。
- `test_prepare_failure_does_not_publish_resource`：embedding 失败映射 INTERNAL，不发布半成品。
- `test_prepare_rejects_unsupported_or_missing_files`：空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。
- `test_prepare_pdf_calls_parser_then_builds_resource`：PDF bytes 交给解析器，返回的 HTML 进入真实资源构建（调用 embedding 说明已建索引）。
- `test_parser_failure_identifies_file_and_does_not_build_index`：解析异常映射 INTERNAL 并标明文件，不进入索引构建。

embedding 替身同时提供 encode 与 tokenize，资源构建复用同一个实例，不再注入独立 get_tokenizer。
