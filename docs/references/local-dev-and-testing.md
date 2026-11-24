# 本地开发、测试与环境参考

归属 [AGENTS.md](../../AGENTS.md)，记录本仓库跨会话复用的本地启停、测试命令、环境避坑与文档审计入口。

## 安装与启停

- Python 环境统一使用 Conda `agent-gate`（Python 3.11）。
- 安装依赖并构建前端：[scripts/install.sh](../../scripts/install.sh)。
- 一键启停 5 个本地服务（`storage` / `agent` / `document_service` / `backend` / `frontend`）：[scripts/start.sh](../../scripts/start.sh)。
- 默认单用户本地运行态：SQLite 数据库为 `backend/backend.sqlite3`，本地对象存储在 `storage/data/`。
- CI 配置见 [.github/workflows/ci.yml](../../.github/workflows/ci.yml) 与 [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)。

## 本地测试命令

- 文档门禁、脚本与 CI 测试：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q`
- `agent` / `document_service` / `backend` / `storage` / `shared` 本地回环测试（显式绕开系统代理）：
  `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost conda run -n agent-gate python -m pytest <target_tests> -q`
- 前端单测与 Lint：`pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`

## 常见环境坑与提交注意

- Hugging Face 公开模型下载若因本机隐式 token 报 401，在根目录 `.env` 中设置 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`。
- 本地运行态目录 `storage/data/` 保持未跟踪，创建 commit 时不要误暂存。
- 知识库审计与跨端会话扫描：`python3 memory/dream_scan.py --audit`（工具设计见 [memory/docs/DESIGN.md](../../memory/docs/DESIGN.md)，整理流程见 [dreaming/SKILL.md](../../.agents/skills/dreaming/SKILL.md)）。
