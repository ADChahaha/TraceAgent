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
