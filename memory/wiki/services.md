# 服务边界与设计文档入口

归属 [architecture-index.md](architecture-index.md)，记录 7 个顶层包的职责定位、默认端口、核心边界与一手文档锚点；各包长文档已按"索引页 + 同级主题子文件"拆分，改具体模块前沿对应索引按需打开子文件。

## 顶层包与文档入口

| 包目录 | 默认地址 | 职责 | 设计与接口入口 |
| --- | --- | --- | --- |
| `agent_proto/` | - | 共享 gRPC 协议（`traceagent-protocol`） | [DESIGN.md](../../agent_proto/docs/DESIGN.md) |
| `storage/` | `127.0.0.1:9000` | 本地 S3 兼容 HTTP 对象存储（`storage/data`） | [DESIGN.md](../../storage/docs/DESIGN.md) |
| `shared/` | - | `ObjectStore` / `S3ObjectStore` / 归档封装 | [DESIGN.md](../../shared/docs/DESIGN.md) |
| `document_service/` | `127.0.0.1:8002` | PDF/DOCX 解析、文档树与索引 | [总设计](../../document_service/docs/DESIGN.md) / [解析](../../document_service/document_processor/docs/DESIGN.md) / [资源](../../document_service/document_resources/docs/DESIGN.md) |
| `agent/` | `127.0.0.1:8001` | LangGraph 问答 Agent 与只读检索工具 | [总设计](../../agent/docs/DESIGN.md) / [API](../../agent/docs/API.md) / [内核](../../agent/service/file_extraction_agent/docs/DESIGN.md) |
| `backend/` | `127.0.0.1:8000` | SQLite 持久化、`SessionManager` 与 SSE | [设计](../../backend/docs/DESIGN.md) / [Manager](../../backend/docs/SESSION_MANAGER.md) / [API](../../backend/docs/API.md) / [表](../../backend/docs/table.md) |
| `frontend/` | `127.0.0.1:3000` | Next.js 工作台、来源管理与引用高亮 | [DESIGN.md](../../frontend/docs/DESIGN.md) |

## 核心边界与现状

- `document_service` 与 `agent` 互不通过 Python import 交接，仅经 `storage` 共享会话桶 `res_<session_id>`（含 `raw/`、`documents.zip`、`index/`、`manifest.json`）。
- 取消问答直接通过原 gRPC `call.cancel()` 传播，不提供独立取消 RPC。
- `backend` 当前面向单用户本地单进程部署，数据库默认 `backend/backend.sqlite3`，不自动迁移旧 `qa_*` 表。
- 2026-11-24 源码核实的 `backend` 待修缺陷（含 `:memory:` 启动失败、失败工具刷新误判、上传与活跃轮并发、取消收口等 9 项）跟踪在 [backend-bugs-2026-11-24.md](../tasks/backend-bugs-2026-11-24.md)。
