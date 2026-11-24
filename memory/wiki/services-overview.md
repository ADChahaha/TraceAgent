# 服务边界与调用链概览

本页属 [architecture-index.md](architecture-index.md)，仅记录 7 个顶层包的职责定位与端口锚点；修改代码前必须直接读取对应包的 `docs/DESIGN.md`。

## 顶层包与默认端口

| 包目录 | 角色与边界 | 默认地址 | 一手设计 |
| --- | --- | --- | --- |
| `agent_proto/` | 共享 gRPC 契约（`DocumentResourceService`、`AgentService`），独立打包 `traceagent-protocol` | - | [DESIGN.md](../../agent_proto/docs/DESIGN.md) |
| `storage/` | 本地 S3 兼容 HTTP 对象存储（`storage/data`，可切外部 `S3_ENDPOINT_URL`） | `127.0.0.1:9000` | [DESIGN.md](../../storage/docs/DESIGN.md) |
| `shared/` | 共享 `ObjectStore` / `S3ObjectStore` / `ArchiveObjectStore` 客户端封装 | - | [DESIGN.md](../../shared/docs/DESIGN.md) |
| `document_service/` | PDF（MinerU）与 DOCX 解析、Markdown 文件树、OpenVINO embedding 索引构建与资源发布 | `127.0.0.1:8002` | [DESIGN.md](../../document_service/docs/DESIGN.md) |
| `agent/` | 基于 LangGraph 的文档 QA Agent，通过子进程工具只读消费 storage 中的文档与索引 | `127.0.0.1:8001` | [DESIGN.md](../../agent/docs/DESIGN.md) |
| `backend/` | SQLite 会话/资源/轮次持久化、`SessionManager` 串行编排与 SSE 推送 | `127.0.0.1:8000` | [DESIGN.md](../../backend/docs/DESIGN.md) |
| `frontend/` | Next.js 工作台，代理 `/api/backend/*`，管理来源列表、对话流与数字引用原文高亮 | `127.0.0.1:3000` | [DESIGN.md](../../frontend/docs/DESIGN.md) |

## 核心边界约束

- `document_service` 与 `agent` 互不通过 Python import 交接，仅经 `storage` 共享会话桶 `res_<session_id>`（含 `raw/`、`documents.zip`、`index/`、`manifest.json`）。
- 取消问答直接通过原 gRPC `call.cancel()` 传播，不再提供独立 `CancelCompletion` RPC。
- `backend` 当前面向单用户本地单进程部署，数据库默认 `backend/backend.sqlite3`，不自动迁移旧 `qa_*` 表。
