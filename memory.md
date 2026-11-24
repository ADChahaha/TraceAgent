# 项目记忆

更新时间：2026-11-24

## 项目概况

- `agent_gate`（TraceAgent）是多轮文档 QA 工作台，拆分为 `agent_proto`、`storage`、`shared`、`document_service`、`agent`、`backend`、`frontend` 七个顶层包。
- `document_service` 与 `agent` 独立部署，只通过 S3 兼容 `storage` 交接会话资源，不互相 import。
- Python 使用 Conda 环境 `agent-gate`（Python 3.11）；默认单用户本地运行，数据库为 `backend/backend.sqlite3`，对象存储为 `storage/data`。

## 索引

- [协作偏好](memory/preference/workspace-preferences.md)
- [服务、文档与常用命令](memory/wiki/services.md)

## 动态记录

- `memory/notes/`：跨会话踩坑与临时记录
- `memory/tasks/`：未完成事项
- [整理记录](memory/dream-log.md) / `memory/archive/`
