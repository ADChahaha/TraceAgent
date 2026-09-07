# 文档资源 gRPC 测试

真实 DOCX 上传 → 真实 HTML 解析与文档树生成 → 替身 embedding → 发布到 storage 服务（返回资源定位数组）→ 路径问答。通过本机 RPC 验证新资源契约及错误码。

- `test_prepare_real_docx_publishes_complete_resource`：真实多文档上传返回 HTML、文档树、索引和 raw 资源定位数组（type 含 documents/index/raw）。
- `test_prepare_failure_does_not_publish_resource`：embedding 失败映射 INTERNAL，不发布半成品。
- `test_prepare_rejects_unsupported_or_missing_files`：空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。
- `test_qa_uses_prepared_path_without_rebuilding_or_deleting`：两轮真实图执行复用同一资源，不重建向量、不删除 storage 中的对象。
- `test_qa_rejects_unmanaged_resource_path`：缺少 documents/index 定位的资源引用在首事件前返回 INVALID_ARGUMENT。
- `test_qa_rejects_damaged_resource_without_rebuilding`：索引缺失、清单版本错误、引用越界均拒绝执行且不重建（损坏经 s3_store 改写）。
- `test_prepare_pdf_calls_parser_then_builds_resource`：PDF bytes 交给解析器，返回的 HTML 进入真实资源构建。
- `test_parser_failure_identifies_file_and_does_not_build_index`：解析异常映射 INTERNAL 并标明文件，不进入索引构建。

图执行验证使用 ainvoke 和异步模型替身，保留原有资源边界断言。
