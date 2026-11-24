# .github (CI) 关键决策

归属 [CI 设计](DESIGN.md)，记录持续集成工作流与测试覆盖边界的长期取舍。

## 1. CI 强制覆盖干净环境 OCR/embeddings 安装、MinerU CLI 与全栈启动冒烟

- 决定：CI 除运行不依赖真实 LLM/MinerU 的 `backend` 与 `frontend` 单元测试外，强制维护 `agent-ocr-install`（在干净 Ubuntu Python 3.11 runner 安装本地 `./agent_proto`、`./shared`、`./storage`、`agent[dev,embeddings]` 与 `document_service[dev,embeddings]`，校验核心导入和 `mineru --help` 后执行离线回归）以及 `deployment-smoke`（复用 `scripts/install.sh` 与 `scripts/start.sh` 并对 2 个 gRPC Health 和 2 个 HTTP 端点做就绪探活）；由 `.github/tests/test_ci.py` 机械锁定本地共享依赖闭包。
- 原因：仅跑 mock 掉 OCR 与 agent 的单测无法验证干净环境能否正确安装 `mineru[core]`、`torch`、`transformers`、`openvino` 及本地 `traceagent-*` 共享包。
- 排除：在 CI 中只跑 mock 后的 backend/frontend 单测而跳过 OCR/embeddings 安装检查；维护与 `scripts/` 分叉的 CI 专用启动脚本。

## 2. CI pytest 命令指向包级测试目录，不硬编码易过时的子测试路径

- 决定：CI 执行测试统一使用包级目录 `python -m pytest agent/tests document_service/tests shared/tests .github/tests -q`，不逐个枚举包内子模块测试目录。
- 原因：删除旧测试子目录（如 `agent/tests/route_policy_agent`）后，本机工作区可能因残留空目录继续通过，但 Git clean checkout 不保留空目录会立即导致 CI 报路径不存在。
- 排除：在 CI 工作流中硬编码列出各子模块测试子目录路径。

## 3. CI 禁止为 `backend` 配置 `:memory:`，冒烟检查使用临时 SQLite 文件并探活 `/chat/sessions`

- 决定：`deployment-smoke` 使用 `/tmp/traceagent-ci-backend.sqlite3`（启动前先清理旧文件及 `-wal`/`-shm`），并在 `/healthz` 之后额外探活 `GET /chat/sessions`；`backend` 单测 job 移除无效的 `BACKEND_DATABASE_PATH: ":memory:"`；由 `.github/tests/test_ci.py` 机械校验所有 job 不再配置内存库路径。
- 原因：`backend` 的 `ThreadLocalDatabase` 依赖普通文件库 + WAL 与按线程独立连接（详见 [backend/core/DECISIONS.md](../../backend/core/DECISIONS.md)），配置 `:memory:` 会导致启动崩溃；且 `/healthz` 不访问数据库，补探 `/chat/sessions` 可直接端到端验证建表与跨工作线程查询正常。
- 排除：在 CI 中保留 `:memory:` 配置；仅探活 `/healthz` 而不校验 SQLite 查询路径。
