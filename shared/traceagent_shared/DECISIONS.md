# traceagent_shared 关键决策

归属 [共享对象存储设计](../docs/DESIGN.md)，记录共享对象存储与归档封装层的长期取舍。

## 1. 抽离无业务语义的共享对象存储层

- 决定：`traceagent_shared` 仅封装 `ObjectStore`、`S3ObjectStore`、`ArchiveObjectStore`、`CompositeObjectStore` 与 `parse_resource_path`，不理解文档解析、索引或问答业务。
- 原因：消除 `document_service`、`agent`、`backend` 之间的重复 S3 封装，保持三个服务不互相 import。
- 排除：在各服务内分别维护 S3 客户端，或把文档树与 embedding 逻辑放进共享层。

## 2. 仅在实例客户端移除 `add_expect_header` 处理器

- 决定：`S3ObjectStore` 写入完整 bytes 时，仅在当前客户端注销 botocore 默认的 `add_expect_header` 事件处理器，不改动全局 `boto3` 行为，其余签名、重试与状态处理交由 SDK。
- 原因：避免兼容端点或代理未及时返回 `100 Continue` 时每次 `PUT` 固定等待 1 秒（接受服务端拒收时可能已发正文的代价）。
- 排除：全局 monkey-patch `boto3` 或放任每次对象写入承担 1 秒超时等待。
