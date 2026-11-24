# 各包设计与接口文档按需路由

本页属 [architecture-index.md](architecture-index.md)，索引全仓已按"轻量总览索引 + 同级主题子文件"重构的设计与接口文档，便于修改具体模块前按需定位最小阅读面。

## 已分层重构的核心文档

| 包 / 模块 | 轻量总览索引 | 主题子文档目录 | 拆分子主题 |
| --- | --- | --- | --- |
| `agent` 服务 | [DESIGN.md](../../agent/docs/DESIGN.md) | `agent/docs/design/` | 模块边界、部署与取消、资源生命周期与契约 |
| `agent` 接口 | [API.md](../../agent/docs/API.md) | `agent/docs/api/` | 准备与请求、事件与重试、取消与错误码 |
| 问答执行内核 | [DESIGN.md](../../agent/service/file_extraction_agent/docs/DESIGN.md) | `.../docs/design/` | 存储与请求、图状态与循环、模型与事件、工具子进程与部署 |
| 问答工具规范 | [tools.md](../../agent/service/file_extraction_agent/docs/tools.md) | `.../docs/tools/` | 路径与只读文件工具（`ls`/`grep`/`read`）、语义检索（`search_embedding`） |
| `backend` 总设计 | [DESIGN.md](../../backend/docs/DESIGN.md) | `backend/docs/design/` | 调用关系与模块边界、数据访问与生命周期 |
| `SessionManager` | [SESSION_MANAGER.md](../../backend/docs/SESSION_MANAGER.md) | `backend/docs/session_manager/` | 所有权与建轮、资源与串行事务、上下文与 Resume、取消容量与参考 |
| `backend` 数据表 | [table.md](../../backend/docs/table.md) | `backend/docs/table/` | 四张表结构与约束、消息配对与中断顺序 |
| `backend` 接口 | [API.md](../../backend/docs/API.md) | `backend/docs/api/` | 会话/提交/取消、文件与文档读取、Resume 与 SSE |
| 文档解析器 | [DESIGN.md](../../document_service/document_processor/docs/DESIGN.md) | `.../docs/design/` | 入口与分流、PDF MinerU 管线、DOCX 管线 |
| `frontend` 工作台 | [DESIGN.md](../../frontend/docs/DESIGN.md) | `frontend/docs/design/` | 上传队列与会话、流式与状态合并、文档引用/布局/代理 |
| 记忆系统设计 | [DESIGN.md](../docs/DESIGN.md) | `memory/docs/design/` | `dream_scan.py` 扫描、三端匹配与六项门禁 |

## 原生轻量单文件设计文档（无需拆分）

- 协议与存储：[agent_proto](../../agent_proto/docs/DESIGN.md) / [storage](../../storage/docs/DESIGN.md) / [shared](../../shared/docs/DESIGN.md)
- 文档服务与资源：[document_service](../../document_service/docs/DESIGN.md) / [document_resources](../../document_service/document_resources/docs/DESIGN.md) / [document_processor API](../../document_service/document_processor/docs/API.md)
- 问答专题与 CI：[STREAMING_AND_CANCELLATION.md](../../agent/service/file_extraction_agent/docs/STREAMING_AND_CANCELLATION.md) / [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)
