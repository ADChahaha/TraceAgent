# 上传业务入口测试

普通文件数据 → 批次类型校验 → processor 解析 → prepare_resources 发布。

- `test_invalid_batch_never_parses`：批次含不支持的文件时，任何文件都不能开始解析。
- `test_upload_preserves_raw_bytes_and_parsed_document`：解析器收到原字节，发布器同时收到 HTML 和原文件。
- `test_preparation_reuses_model_for_tokenization`：对 OpenVINO/Torch 分别执行两次真实资源构建和发布，确认只构造一个模型，分块与编码共用其 tokenizer。
