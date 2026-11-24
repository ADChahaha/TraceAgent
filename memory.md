# 记忆入口

更新时间：2026-11-24 | 规则见 [AGENTS.md](AGENTS.md)

## 项目概况

- `agent_gate`（TraceAgent）是多轮文档 QA 工作台，拆分为 `agent_proto`、`storage`、`shared`、`document_service`、`agent`、`backend`、`frontend` 七个顶层包。
- `document_service` 与 `agent` 独立部署，只通过 S3 兼容 `storage` 交接会话资源，不互相 import。
- Python 统一用 Conda 环境 `agent-gate`（Python 3.11）；默认单用户本地运行，数据库为 `backend/backend.sqlite3`，对象存储为 `storage/data`。

## 一级索引

- [用户偏好](memory/preference/INDEX.md)
- [项目服务与常用入口](memory/wiki/project-index.md)

## 暂存与归档

- `memory/notes/` / `memory/tasks/` / [dream-log.md](memory/dream-log.md) / `memory/archive/`
