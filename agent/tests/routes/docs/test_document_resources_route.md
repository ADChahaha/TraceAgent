# 文档资源 HTTP 测试

真实 DOCX 上传 → 真实 HTML 解析与文档树生成 → 替身 embedding → 资源发布 → 路径问答，验证两个 HTTP 入口的完整链路。

- `test_prepare_real_docx_publishes_complete_resource`：多文档准备返回完整资源、索引和原文 HTML。
- `test_prepare_failure_does_not_publish_resource`：确认错误来自 embedding 替身，失败不发布资源并清理临时目录。
- `test_prepare_rejects_unsupported_file`：不支持的上传格式返回 422，不创建资源。
- `test_qa_uses_prepared_path_without_rebuilding_or_deleting`：两轮问答复用同一路径，不重建文档向量、不删除资源。
- `test_qa_rejects_unmanaged_resource_path`：问答拒绝受管理目录之外的路径。
- `test_qa_rejects_damaged_resource_without_rebuilding`：索引缺失、清单版本不支持或引用越界均返回 422，不触发文档向量重建。
- `test_old_processing_endpoints_removed`：旧解析 HTTP 入口均删除，统一走资源准备接口。
- `test_prepare_pdf_calls_parser_then_builds_resource`：PDF 上传交给解析器后实际生成文件树和文档向量。
- `test_parser_failure_identifies_file_and_does_not_build_index`：解析失败显示文件和原因，不进入索引构建。

资源基础实现导入迁移到 `service.document_resources`。
