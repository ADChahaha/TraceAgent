# 会话资源入口测试

prepare_session_resources 的真实输入是 session_id + 上传文件 + remove_raw；桶内 raw 是事实来源，上传增量构建，纯删除裁剪既有产物。单元测试用本地 DirectoryObjectStore 与 processor/publish_resources 替身隔离会话语义；真实构建与发布链路由 route 测试和 tokenization 测试覆盖。

- `test_upload_writes_raw_to_session_bucket_and_publishes_parsed_documents`：新批次写入会话桶 `raw/`，publish 收到按文件解析出的 HTML，返回的 raw 引用指向固定桶。
- `test_second_upload_reuses_bucket_and_keeps_previous_raws`：同一 session 二次上传不新建桶，返回新旧 raw 的全量引用，publish 只收到新批次文档。
- `test_remove_raw_with_empty_files_deletes_object_and_prunes`：空批次 + remove_raw 合法（backend remove_file 的调用形状），桶内目标被删除，调用裁剪而不调用全量 publish。
- `test_remove_last_raw_clears_published_artifacts`：移除最后一个 raw 返回空引用，不再调用 publish，桶内 raw 与 index/ 前缀对象清空，documents.zip/manifest 删除。
- `test_unknown_remove_target_is_ignored`：remove_raw 指向桶内不存在的文件时幂等跳过，不影响其余资源。
- `test_same_name_upload_replaces_raw`：同名上传覆盖桶内 raw 字节，引用仍只有一个。
- `test_empty_request_without_removal_is_rejected`：files 与 remove_raw 全空时拒绝（纯空请求无意义）。
- `test_invalid_session_id_is_rejected`：空、空白、含路径分隔符或 `.`/`..` 的 session_id 一律拒绝，防止推导出不安全的桶名。
- `test_remove_raw_must_be_raw_in_session_bucket`：type 非 raw、桶不匹配、非 s3:// 定位都被拒绝。
- `test_upload_parses_only_new_files`：第二次上传只解析新 b.pdf，旧 a.pdf 不重复解析。
- `test_upload_rejects_invalid_filename_or_content`：空文件名、路径分隔符、空内容在写桶前失败，不产生半成品。
- `test_invalid_batch_never_parses`：合并后批次含不支持类型时，任何文件都不开始解析。
- `test_failed_parse_leaves_session_bucket_unchanged`：解析失败发生在任何写桶之前，会话桶保持原状（无孤儿 raw、已发布产物不变），坏文件不毒化同一会话的后续上传。
- `test_preparation_reuses_model_for_tokenization`：对 OpenVINO/Torch 分别执行两次真实构建发布，确认只构造一个模型，分块与编码共用其 tokenizer；publish 已改为显式传入 store 与桶名。

- `indexed`：使用真实发布器和确定性向量建立三个文件，再禁止解析、模型加载及 raw 下载，验证删除复用路径。
- `test_remove_reuses_vectors_and_preserves_paths_across_repeated_deletes`：分别从新旧清单连续删除首个、第二个和最后一个文件，逐字节核对剩余正文，逐行核对向量和分块，确认路径不重编号且最后清空产物。
- `test_remove_invalid_index_leaves_raw_and_published_objects_unchanged`：损坏向量文件时删除失败，raw 和已发布对象均不修改。
- `test_remove_multiple_and_unknown_targets_without_rebuilding`：批量删除包含未知文件，保留正确 raw；重复删除同一目标保持既有产物不变。

- `test_remove_preserves_empty_document_without_vectors`：无正文的文档没有归档目录或向量行，删除仍成功并保留剩余 raw。

- `test_upload_only_encodes_new_documents_and_preserves_existing_artifacts`：新旧清单均只解析和编码新批次，禁止下载旧 raw；核对旧路径、正文、分块和向量保持，继续覆盖同名替换与同时删除，不产生重复 chunk_id。
- `test_failed_incremental_embedding_keeps_all_objects_unchanged`：补传 embedding 失败时，原文件与已发布对象逐字节保持，不留下新 raw。
- `test_incremental_upload_handles_documents_without_chunks`：空正文与正常文档按两种顺序上传，索引维度正确，之后删除正文文档仍保留空文档。
