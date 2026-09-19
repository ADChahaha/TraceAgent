# 共享对象存储设计

业务层通过 ObjectStore 的 bucket/key 接口读写 S3 对象，S3ObjectStore 使用独立 boto3 客户端，按环境配置 endpoint 和桶名前缀。资源 URL 由 parse_resource_path 校验并拆分；具体文档及索引语义由调用方管理。

写入接收已经准备好的 bytes，直接发送完整请求体。客户端取消 botocore 默认的 add_expect_header 事件处理器，避免兼容端点或代理未及时返回 100 Continue 时，每次 PUT 固定等待 1 秒。该调整只作用于当前 S3ObjectStore 的客户端，不改全局 boto3 行为；签名、重试、校验和及 HTTP 状态处理仍由 SDK 执行。代价是服务器拒绝请求时，客户端可能已经发送正文。

get_object 返回完整 bytes，NoSuchKey 返回 None；head_object 返回大小或 None。ArchiveObjectStore 在内存中读取 zip；CompositeObjectStore 将 documents 前缀路由到归档，其余键路由到 S3。共享层不构建 embedding，也不改变文档归档内容。
