# scripts 关键决策

归属 [本地开发、测试与环境参考](../../docs/references/local-dev-and-testing.md) 与 [设计文档总目](../../docs/design-docs/index.md)，记录本地安装与多服务启停脚本的长期取舍。

## 1. 拆分为无 `.env` 的 `install.sh` 与生产模式 `start.sh`，取消带 `--reload` 的 `dev.sh`

- 决定：取消带 `--reload` 的开发启动脚本，拆分为只负责安装依赖与构建前端的 [install.sh](../install.sh)（不读取 `.env`）和读取根目录 `.env`、以生产模式启动全部服务的 [start.sh](../start.sh)（不带 `--reload`，子进程使用 `exec` 并在退出清理前解除信号 trap）；未配置非空 `S3_ENDPOINT_URL` 时自动先启动本地 `storage` 并向其余服务导出同一地址，已配置时直接复用外部 S3 服务。
- 原因：分离无状态安装构建与有状态运行配置，避免 uvicorn `--reload` watcher 高 CPU 放大请求卡顿，同时让本地一键启动与 CI `deployment-smoke` 复用完全相同的脚本。
- 排除：保留单脚本混杂依赖安装与热重载开发启动；或在未配置外部 S3 时要求用户另开终端手工启动本地对象存储。
