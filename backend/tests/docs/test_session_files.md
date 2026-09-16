# test_session_files.py

临时 SQLite -> SessionRegistry/SessionManager -> FakeAgent（兼作 document service 替身）-> 比对资源行、agent 调用参数和资源事件。上传/删除业务在 manager：校验、document service 调用和资源替换都不经 registry。

- `test_create_session_starts_ready_without_turns`：create_session 建出 ready 且无活跃轮的会话行，随后可正常发起轮次。
- `test_manager_upload_validates_before_document_call`：manager 的 upload_files 校验空列表、非法后缀和空内容，校验失败不触达 document service。
- `test_upload_materializes_at_upload_and_binds_to_session`：物化在上传时发生并携带 session_id，快照与轮次请求使用替换后的资源引用；轮次不重复准备。
- `test_upload_rejects_bad_type_limits_and_unknown_session`：类型限制、累计文件数、累计字节数和未知会话各自返回对应错误；未知会话在 get_or_create 即拒绝。
- `test_resources_persist_across_turns_without_replacement`：连续两轮的 resource_path 完全一致，轮次不替换、不准备资源，资源行数不变。
- `test_delete_removes_raw_and_rebuilds_bundle`：删除调用 document service 时 files 为空、remove_raw 指向被删文件；删除后 bundle 引用不含该 raw；对缺失资源和不支持删除的 bundle 引用分别返回 NotFound 与 ValidationError。resource_path 只含 bundle 引用。
- `test_read_block_returns_block_text_from_session_bundle`：manager.read_block 从本会话 documents 引用解析 bucket 转发 document client；归档内 key 返回原文，缺失 key 或没有归档的会话返回 NotFound。
- `test_upload_broadcasts_resources_prepared_to_subscribers`：资源替换后向已注册订阅者广播 resources.prepared，payload 携带非 raw 的 bundle 引用。
- `test_download_file_returns_raw_bytes_and_rejects_missing_and_bundle`：download_file 按 raw 资源行经 ObjectStore 读回原始字节；对不存在资源和 bundle 引用分别返回 NotFound 与 ValidationError。
- `test_list_and_read_processed_documents_from_archive`：list_documents 列出 documents.zip 归档内的 md key 与字节大小；read_document 复用 ReadBlocks 取整文件全文，缺失 key 与无归档会话返回 NotFound。
- `test_concurrent_uploads_serialize_and_enforce_quota`：并发上传作为队列命令串行执行，第二笔基于第一笔替换后的资源状态做配额判定并被拒绝，document service 只收到一方的调用，资源表只留胜者的 raw。
