# 文档资源 gRPC 测试

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

独立 document service 的真实 DOCX 上传 → 真实 HTML 解析与文档树生成 → 替身 embedding → 发布到 storage 服务（返回资源定位数组）。本文件只验证 document service 的 RPC、资源契约及错误码；agent 的消费链路见 `test_agent_resource_integration.py`。

每个测试通过 `session_id` fixture 取独立会话 id，资源进入各自的 `res_<session_id>` 桶，互不污染；`prepare` 辅助函数按 backend 的真实调用形状发送 session_id/files/remove_raw。

- `test_prepare_real_docx_publishes_complete_resource`：真实多文档上传发布单个 `documents.zip` 和独立的 manifest/index/vectors/raw 对象，桶名等于 `res_<session_id>`，不在桶里散落 `documents/` 前缀对象，也不内联返回 HTML。
- `test_second_upload_reuses_session_bucket_and_keeps_previous_raws`：同一会话两次上传使用同一桶，第二次响应包含新旧全部 raw 引用。
- `test_remove_raw_with_empty_files_deletes_object_and_rebuilds`：空批次 + remove_raw 删除桶内 raw 并用剩余文件重建，归档与索引仍然可用。
- `test_remove_last_raw_clears_published_artifacts`：移除最后一个 raw 返回空引用，桶内对象全部清空。
- `test_remove_raw_rejects_other_bucket_or_type`：remove_raw 的 type 非 raw、桶不匹配或非 s3:// 定位返回 INVALID_ARGUMENT。
- `test_prepare_requires_session_id`：缺少 session_id 无法确定会话桶，返回 INVALID_ARGUMENT。
- `test_protocol_prepare_response_drops_documents_payload`：`PrepareResourcesResponse` 只保留 `resource_path`，`documents` 字段与 `Document` 消息已从协议移除。
- `test_prepare_failure_does_not_publish_resource`：embedding 失败映射 INTERNAL，不发布半成品。
- `test_prepare_rejects_unsupported_or_missing_files`：空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。
- `test_prepare_pdf_calls_parser_then_builds_resource`：PDF bytes 交给解析器，返回的 HTML 进入真实资源构建，发布到会话桶（调用 embedding 说明已建索引）。
- `test_parser_failure_identifies_file_and_does_not_build_index`：解析异常映射 INTERNAL 并标明文件，不进入索引构建。
- `test_failed_upload_does_not_poison_session`：解析失败不写 raw，同一会话的后续上传不被坏文件永久卡死。
- `test_read_blocks_returns_block_text_from_archive`：归档内 key 返回原文；不存在的 key 返回 found=false。
- `test_read_blocks_requires_bucket_and_keys`：空 bucket 或空 keys 返回 INVALID_ARGUMENT。
- `test_read_blocks_missing_archive_is_not_found`：归档缺失（未上传会话）返回 NOT_FOUND。

对缺失对象的检查使用 list_objects/head_object 而非 get_object：storage 当前对缺失 key 返回非 S3 XML 错误体，boto3 `NoSuchKey` 分支不触发（见 DEVLOG 已知问题）。

embedding 替身同时提供 encode 与 tokenize，资源构建复用同一个实例，不再注入独立 get_tokenizer。

- `test_server_warms_embedding_before_becoming_available`：生产启动模式在返回可启动服务前完成一次短文本编码，首次上传复用预热模型。
