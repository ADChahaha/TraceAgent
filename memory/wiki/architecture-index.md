# 系统架构与服务索引（L1）

本页汇总 TraceAgent 各服务边界与一手设计文档路由（顶层入口见 [memory.md](../../memory.md)）。

## 页面路由

| 查找需求 | 目标页（L2） | 核心覆盖 |
| --- | --- | --- |
| 7 个顶层包职责、端口、调用链与一手设计入口 | [services-overview.md](services-overview.md) | `agent_proto` / `storage` / `shared` / `document_service` / `agent` / `backend` / `frontend` 边界与端口 |

## 一手设计文档锚点

- 总览与启动说明：[README.md](../../README.md)
- 协议与基础设施：[agent_proto](../../agent_proto/docs/DESIGN.md) / [storage](../../storage/docs/DESIGN.md) / [shared](../../shared/docs/DESIGN.md)
- 核心业务服务：[document_service](../../document_service/docs/DESIGN.md) / [agent](../../agent/docs/DESIGN.md) / [backend](../../backend/docs/DESIGN.md) / [frontend](../../frontend/docs/DESIGN.md)
- 持续集成与脚本：[.github/docs/DESIGN.md](../../.github/docs/DESIGN.md) / [scripts/docs/DEVLOG.md](../../scripts/docs/DEVLOG.md)
