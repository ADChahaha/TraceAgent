# 记忆总入口（L0）

更新时间：2026-11-24 | 规则见 [AGENTS.md](AGENTS.md) | 按需沿下方 L1 索引逐层下钻，勿全量读取。

## 全局锚点与硬红线

- **项目定位**：`agent_gate`（TraceAgent），基于只读文档虚拟仓库与数字引用的多轮文档 QA 工作台。
- **服务拆分**：7 个顶层包（`agent_proto`、`storage`、`shared`、`document_service`、`agent`、`backend`、`frontend`），`document_service` 与 `agent` 独立部署并通过 S3 兼容 `storage` 交接资源，不互相 import。
- **本地运行与环境**：Python 统一使用 Conda 环境 `agent-gate`（Python 3.11）；默认单用户本地运行，SQLite 为 `backend/backend.sqlite3`，对象存储在 `storage/data`。
- **工程红线**：修改代码前先读目标文件与最近 `docs/DESIGN.md`；行为变更严格执行 `red -> green -> refactor` TDD 并同步设计文档、开发日志与 `tests/docs/`，完成后创建原子 commit。

## 一级领域路由（L1，按需打开）

| 任务域 | L1 入口 | 涵盖主题 |
| --- | --- | --- |
| 用户偏好 | [preference/INDEX.md](memory/preference/INDEX.md) | 交流语言、记忆分层预算、长文档拆分与 Dreaming 提交习惯 |
| 架构与服务 | [architecture-index.md](memory/wiki/architecture-index.md) | 7 个包职责边界、端口契约与一手 `docs/DESIGN.md` 路由 |
| 工作区与维护 | [workspace-index.md](memory/wiki/workspace-index.md) | 仓库目录地图、环境与测试入口、`dream_scan.py` 用法与门禁 |

## 动态区与底层一手资料

- **活跃暂存**：`memory/notes/`（会中预判） / `memory/tasks/`（未完任务） / [dream-log.md](memory/dream-log.md)
- **一手资料**：[README.md](README.md) / [memory/docs/DESIGN.md](memory/docs/DESIGN.md) / `memory/archive/`
