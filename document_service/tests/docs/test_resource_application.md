# 会话资源入口测试

prepare_session_resources 的真实输入是 session_id + 上传文件 + remove_raw；桶内 raw 是事实来源，先合并再全量重建。单元测试用本地 DirectoryObjectStore 与 processor/publish_resources 替身隔离会话语义；真实构建与发布链路由 route 测试和 tokenization 测试覆盖。

- `test_upload_writes_raw_to_session_bucket_and_publishes_parsed_documents`：新批次写入会话桶 `raw/`，publish 收到按文件解析出的 HTML，返回的 raw 引用指向固定桶。
- `test_second_upload_reuses_bucket_and_keeps_previous_raws`：同一 session 二次上传不新建桶，返回新旧 raw 的全量引用，publish 收到合并后的全部文档。
- `test_remove_raw_with_empty_files_deletes_object_and_rebuilds`：空批次 + remove_raw 合法（backend remove_file 的调用形状），桶内对象被删除，publish 只收到剩余文件。
- `test_remove_last_raw_clears_published_artifacts`：移除最后一个 raw 返回空引用，不再调用 publish，桶内 raw 与 index/ 前缀对象清空，documents.zip/manifest 删除。
- `test_unknown_remove_target_is_ignored`：remove_raw 指向桶内不存在的文件时幂等跳过，不影响其余资源。
- `test_same_name_upload_replaces_raw`：同名上传覆盖桶内 raw 字节，引用仍只有一个。
- `test_empty_request_without_removal_is_rejected`：files 与 remove_raw 全空时拒绝（纯空请求无意义）。
- `test_invalid_session_id_is_rejected`：空、空白、含路径分隔符或 `.`/`..` 的 session_id 一律拒绝，防止推导出不安全的桶名。
- `test_remove_raw_must_be_raw_in_session_bucket`：type 非 raw、桶不匹配、非 s3:// 定位都被拒绝。
- `test_rebuild_parses_all_session_raws`：每次调用重新解析桶内全部 raw（全量重建语义），第二次调用解析已有 a.pdf 和新 b.pdf。
- `test_upload_rejects_invalid_filename_or_content`：空文件名、路径分隔符、空内容在写桶前失败，不产生半成品。
- `test_invalid_batch_never_parses`：合并后批次含不支持类型时，任何文件都不开始解析。
- `test_preparation_reuses_model_for_tokenization`：对 OpenVINO/Torch 分别执行两次真实构建发布，确认只构造一个模型，分块与编码共用其 tokenizer；publish 已改为显式传入 store 与桶名。
