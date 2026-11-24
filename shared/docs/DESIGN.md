# 共享对象存储与配置设计

`traceagent_shared` 负责两类无业务语义的共享基础设施：对象存储封装（`object_store.py`）与全仓统一配置加载器（`config.py`）。

## 统一配置（`config.toml`）

- 配置文件以仓库根目录 `config.toml` 为单一入口（模板见根目录 `config.example.toml`），使用 Python 3.11 标准库 `tomllib` 解析，不引入额外第三方依赖。
- 优先级固定为：显式进程环境变量 > `config.toml` > 代码默认值。支持通过 `TRACEAGENT_CONFIG` 指定路径（空串表示禁用文件加载），未指定时依次检查当前工作目录与仓库根目录的 `config.toml`。
- 入口 `python -m traceagent_shared.config --shell-exports <path>` 为 `scripts/start.sh` 输出安全转义的环境变量导出语句；`apply_runtime_env()` 负责按不覆盖原则注入影响第三方 SDK 的运行期环境变量（如 `HF_HUB_DISABLE_IMPLICIT_TOKEN`）。

## 对象存储

业务层通过 ObjectStore 的 bucket/key 接口读写 S3 对象，S3ObjectStore 使用独立 boto3 客户端，按 `config.toml` 与环境变量配置 endpoint、凭据和桶名前缀。资源 URL 由 parse_resource_path 校验并拆分；具体文档及索引语义由调用方管理。

写入接收已经准备好的 bytes，直接发送完整请求体。客户端取消 botocore 默认的 add_expect_header 事件处理器，避免兼容端点或代理未及时返回 100 Continue 时，每次 PUT 固定等待 1 秒。该调整只作用于当前 S3ObjectStore 的客户端，不改全局 boto3 行为；签名、重试、校验和及 HTTP 状态处理仍由 SDK 执行。代价是服务器拒绝请求时，客户端可能已经发送正文。

get_object 返回完整 bytes，NoSuchKey 返回 None；head_object 返回大小或 None。ArchiveObjectStore 在内存中读取 zip；CompositeObjectStore 将 documents 前缀路由到归档，其余键路由到 S3。共享层不构建 embedding，也不改变文档归档内容。

相关：[traceagent_shared/DECISIONS.md](../traceagent_shared/DECISIONS.md)
