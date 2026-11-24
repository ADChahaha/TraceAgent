# traceagent_shared 关键决策

归属 [共享对象存储设计](../docs/DESIGN.md)，记录共享对象存储与归档封装层的长期取舍。

## 1. 抽离无业务语义的共享基础设施层（对象存储与 `config.toml` 加载器）

- 决定：`traceagent_shared` 仅封装 `ObjectStore`、`S3ObjectStore`、`ArchiveObjectStore`、`CompositeObjectStore`、`parse_resource_path` 与基于 Python 3.11 标准库 `tomllib` 的单文件配置加载器 `config.py`，不理解文档解析、索引或问答业务。
- 原因：消除 `storage`、`document_service`、`agent`、`backend` 之间的重复 S3 封装与分散配置解析，保持业务服务不互相 import。
- 排除：在各服务内分别维护 S3 客户端或独立配置解析逻辑，或把文档树与 embedding 逻辑放进共享层。

## 2. 仅在实例客户端移除 `add_expect_header` 处理器

- 决定：`S3ObjectStore` 写入完整 bytes 时，仅在当前客户端注销 botocore 默认的 `add_expect_header` 事件处理器，不改动全局 `boto3` 行为，其余签名、重试与状态处理交由 SDK。
- 原因：避免兼容端点或代理未及时返回 `100 Continue` 时每次 `PUT` 固定等待 1 秒（接受服务端拒收时可能已发正文的代价）。
- 排除：全局 monkey-patch `boto3` 或放任每次对象写入承担 1 秒超时等待。

## 3. 全仓配置由 `.env` 切换为单文件 `config.toml` 加进程环境变量覆盖

- 决定：全仓运行配置统一收口到仓库根目录 `config.toml`（根目录提供无密钥模板 `config.example.toml`，`.gitignore` 忽略 `config.toml`），由 `traceagent_shared.config` 基于标准库 `tomllib` 读取，并提供 `--shell-exports` CLI 供 `scripts/start.sh` 导出；移除运行态对 `.env` 的读取，保留显式进程环境变量对配置文件的覆盖能力与 `TRACEAGENT_CONFIG` 路径覆写。
- 原因：TOML 分段结构清晰表达 `[model]`、`[title_model]`、`[storage]`、`[agent]`、`[document_service]`、`[backend]`、`[frontend]`、`[huggingface]` 的归属与类型，避免 `.env` 扁平键值散落与引号/类型歧义，同时零新增第三方依赖。
- 排除：继续沿用扁平 `.env` 并引入 `python-dotenv`；或引入外部配置中心与多环境文件继承体系。
