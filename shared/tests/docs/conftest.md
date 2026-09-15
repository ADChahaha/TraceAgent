# shared 测试夹具

`storage_server` 启动本地 S3-compatible storage，`s3_store` 使用 `traceagent_shared.object_store` 访问它，验证共享对象存储实现而不依赖外部 MinIO 或 AWS。
