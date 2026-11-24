# storage/core 关键决策

归属 [Storage 设计](../docs/DESIGN.md)，记录本地 S3 兼容存储核心模块的长期取舍。

## 1. 用纯 Python 本地 S3 兼容 HTTP 服务作为服务间文件交接层

- 决定：由 `DirectoryObjectStore` 将 `bucket/key` 映射到本地目录，通过 FastAPI 暴露 S3 wire 协议；首版不做签名鉴权、版本、副本、配额与加密。
- 原因：让 `document_service`、`agent`、`backend` 统一用 `boto3` 和 `s3://<bucket>/<key>` 语义存取文件，未来切换真实 S3 或 MinIO 只需替换 `S3_ENDPOINT_URL`，无需改业务代码。
- 排除：让多服务直接共享本机绝对文件路径，或在本地开发阶段强依赖外部容器化 MinIO。

## 2. 严格路径白名单与标准 S3 XML 错误码

- 决定：`_bucket_dir` 走小写字母/数字/下划线/连字符白名单并校验为数据根直接子目录，`_obj_path` 拒绝空串、`.`、绝对路径与 `..` 逃逸；缺失与非法访问返回标准 S3 XML Error（`NoSuchKey`、`InvalidBucketName`、`InvalidKey`）。
- 原因：防止目录逃逸并保证 `boto3` 客户端能够按标准错误码区分缺失对象（映射为 `None`）与系统异常。
- 排除：返回自定义 JSON 错误结构或跳过路径归一化校验。
