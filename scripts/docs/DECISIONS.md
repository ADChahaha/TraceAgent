# scripts 关键决策

归属 [本地开发、测试与环境参考](../../docs/references/local-dev-and-testing.md) 与 [设计文档总目](../../docs/design-docs/index.md)，记录本地安装与多服务启停脚本的长期取舍。

## 1. 拆分为无配置的 `install.sh` 与读取 `config.toml` 的生产模式 `start.sh`，取消带 `--reload` 的 `dev.sh`

- 决定：取消带 `--reload` 的开发启动脚本，拆分为只负责安装依赖与构建前端的 [install.sh](../install.sh)（不读取配置文件）和读取根目录 `config.toml`（支持 `CONFIG_FILE` / `TRACEAGENT_CONFIG` 覆写）、经 `python -m traceagent_shared.config --shell-exports` 导出环境变量并以生产模式启动全部服务的 [start.sh](../start.sh)（不带 `--reload`，子进程使用 `exec` 并在退出清理前解除信号 trap）；未配置非空 `storage.endpoint_url`（或 `S3_ENDPOINT_URL`）时自动先启动本地 `storage` 并向其余服务导出同一地址，已配置时直接复用外部 S3 服务。
- 原因：分离无状态安装构建与有状态运行配置，避免 uvicorn `--reload` watcher 高 CPU 放大请求卡顿，同时让本地一键启动与 CI `deployment-smoke` 复用完全相同的脚本。
- 排除：保留单脚本混杂依赖安装与热重载开发启动；或在未配置外部 S3 时要求用户另开终端手工启动本地对象存储。

## 2. 将仓库文档门禁拆为 `scripts/check_docs.py`，个人记忆与整理技能留在本地忽略

- 决定：公开仓库的文档完整性校验（顶层骨架、断链与中文锚点、全仓模块 `DECISIONS.md` 收录、归档计划决策迁出与文风预算）独立落位在 [check_docs.py](../check_docs.py) 及 [test_check_docs.py](../tests/test_check_docs.py)；个人本地记忆目录 `memory/` 与个人跨端会话整理技能 `.agents/` 全部加入 `.gitignore` 并从 Git 取消追踪，仅在开发机本地保留。
- 原因：参考 OpenAI Harness Engineering 与 Anthropic Claude Code 实践，进入 Git 的应仅为经核实可跨人/跨机复用的仓库工程文档、模块决策与机械门禁；个人会话回顾流水、临时草稿和本机三端 transcript 扫描工具属于个人工作痕迹，不应污染公开 MIT 仓库目录树与提交历史。
- 排除：将个人 `memory/` 目录与整理流水继续提交到公开仓库；或在移除 `memory/` 时顺带放弃仓库级文档断链与 `DECISIONS.md` 索引机械门禁。

## 3. 新增 `scripts/check_architecture.py` 机械锁死单文件 300 行上限与分层/依赖倒置（DIP）架构边界

- 决定：参考 OpenAI Harness Engineering 实践，新增 [check_architecture.py](../check_architecture.py) 及模块化规则集 `scripts/arch_lint/`，并在 `.github/workflows/ci.yml` 的 `repo-gates` job 中强制执行：(1) 全仓所有非忽略手写代码文件（`.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.css`，含测试文件，仅豁免自动生成的 `*_pb2.py`/`*_pb2_grpc.py`/`*_pb2.pyi` 与构建/依赖目录）不得超过 300 行，0 豁免；(2) 基于 Python AST 强制校验顶层 7 包单向分层、各包内固定分层（如 `backend` 禁止 `routes` 跳过 `services` 直连 `crud`，`document_service` 保持 `schemas -> protocols -> domain -> application -> routes -> main`）与依赖倒置原则（业务服务与路由仅依赖 `Protocol` 抽象，禁止直接导入具体 gRPC 客户端或 `S3ObjectStore`/`build_s3_object_store`，具体绑定收口于各包 `main.py` 装配根）；(3) 校验前端单向分层（`session-types -> lib -> ui -> components -> app`）、零循环依赖与代理端口边界；(4) 所有报错输出面向人与 Agent 的可执行修复指引与文档指针。
- 原因：靠人工 review 与口头约定难以长期维持大文件拆分和依赖倒置纪律；在 CI 与本地以毫秒级静态门禁自动拦截违规并给出明确修复方向，才能在高频演进中防止架构漂移。
- 排除：仅对生产代码限制行数而放任 CSS/测试文件膨胀；对历史超长文件留白名单而不清理死代码；在服务层或路由层继续按需懒构造具体 S3/gRPC 实现。
