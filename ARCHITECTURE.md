# TraceAgent 顶层架构与包分层

本页是仓库的顶层领域地图与依赖边界（配合 [AGENTS.md](AGENTS.md) 与 [设计文档总目](docs/design-docs/index.md) 使用）。

## 领域地图（7 个顶层包）

| 顶层包 | 默认监听 | 领域职责 | 禁止承担 |
| --- | --- | --- | --- |
| `agent_proto/` | 无 | 唯一共享 gRPC 契约（`traceagent-protocol` wheel） | 不依赖任何业务包 |
| `storage/` | `127.0.0.1:9000` | 本地纯 Python S3 兼容 HTTP 对象存储（`storage/data`） | 不 import 业务代码，不理解文档或会话语义 |
| `shared/` | 无 | 共享 `ObjectStore` / `S3ObjectStore` / 归档封装（`traceagent-shared`） | 不含文档解析、向量构建或问答逻辑 |
| `document_service/` | `127.0.0.1:8002` | PDF/DOCX 解析、Markdown 树、分块向量化与资源发布 | 不 import `agent`，不暴露用户 HTTP API |
| `agent/` | `127.0.0.1:8001` | 无状态单轮 LangGraph 文档问答与子进程只读工具 | 不 import `document_service`，不管理多轮会话状态 |
| `backend/` | `127.0.0.1:8000` | SQLite 持久化、`SessionManager` / `TurnRuntime` 编排与 SSE | 不做文档解析与模型推理，不透传 `raw` 给 `agent` |
| `frontend/` | `127.0.0.1:3000` | Next.js 工作台、来源管理、流式投影与原文引用高亮 | 不直连 `storage`/`agent`/`document_service`，只经 `/api/backend/*` 代理 |

## 单向分层与运行时拓扑

代码静态依赖严格单向向下，平级业务服务之间互不 import：

```text
第 1 层（契约与存储基础）: agent_proto / storage / shared
                                ^
第 2 层（独立 gRPC 服务）: document_service    agent   （两者互不 import，仅经 storage 桶 res_<session_id> 交接）
                                ^                ^
第 3 层（会话编排网关）  :            backend          （通过两个 gRPC client 分别调用，持有 SQLite 状态）
                                         ^
第 4 层（展示与交互）    :            frontend         （经 Next.js 代理访问 backend HTTP / SSE）
```

## 关键架构不变量

- 产品与仓库定位：系统已从早期固定 Schema 字段抽取与人工审核门禁转型为多轮可追溯文档 QA 工作台（保留历史仓名 `agent_gate` 与模块名 `file_extraction_agent`），不再保留字段路由或审批兼容层；7 个顶层包维持单仓库统一演进。
- 服务交接与存储隔离：文件与处理产物统一落入 `storage` 会话桶 `res_<session_id>`（含 `raw/`、`documents.zip`、`index/`、`manifest.json`）；原始 PDF/DOCX 二进制绝不存入 SQLite；`document_service` 生产，`agent` 只读消费，两者严禁直连 `backend` 的 SQLite 数据库；用户级文件删除入口统一收口于 `backend`。
- 协议与取消：仅暴露 `DocumentResourceService.PrepareResources`、`DocumentResourceService.ReadBlocks`、`AgentService.ChatCompletion`、`AgentService.GenerateTitle` 与标准 gRPC Health；取消统一经原 gRPC `call.cancel()` 沿异步 Task 传播，不维护远端活动任务表。
- 数据所有权与终态裁决：`backend` 是跨服务异步控制流与轮次终态的唯一事实源，`agent` 仅作无状态执行器产出候选事件，`call.cancel()` 仅作尽力资源清理；`backend` 写入统一经 `crud.transaction()` 原子提交，过程增量只走内存 `TurnView` 与 SSE 广播不落库；前端以 `GET /resume` 快照为事实来源，重连不重发 `POST`。
- 部署与演进边界：当前面向单用户本地单进程部署（入口见 [scripts/start.sh](scripts/start.sh)）；新增能力优先通过新增独立模块或清晰扩展点承接，不破坏各模块 `DECISIONS.md` 既有契约。

相关：[设计文档总目](docs/design-docs/index.md) / [核心工程原则](docs/design-docs/core-beliefs.md) / [产品规格](docs/product-specs/index.md) / [技术债台账](docs/exec-plans/tech-debt-tracker.md)
