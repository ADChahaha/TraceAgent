# 系统架构与服务索引（L1）

本页汇总 TraceAgent 各服务边界与一手设计文档路由（顶层入口见 [memory.md](../../memory.md)）。

## 页面路由

| 查找需求 | 目标页（L2） | 核心覆盖 |
| --- | --- | --- |
| 7 个顶层包职责、端口、调用链与边界 | [services-overview.md](services-overview.md) | `agent_proto` / `storage` / `shared` / `document_service` / `agent` / `backend` / `frontend` 边界与端口 |
| 全仓重构后的设计与接口文档按需路由 | [docs-map.md](docs-map.md) | 11 份已拆分为"索引 + 主题子文件"的设计/API 文档及轻量单文件入口 |

## 一手总览锚点

- 项目总览与启动：[README.md](../../README.md)
- 核心服务索引：[document_service](../../document_service/docs/DESIGN.md) / [agent](../../agent/docs/DESIGN.md) / [backend](../../backend/docs/DESIGN.md) / [frontend](../../frontend/docs/DESIGN.md)
- 协议、存储与 CI：[agent_proto](../../agent_proto/docs/DESIGN.md) / [storage](../../storage/docs/DESIGN.md) / [shared](../../shared/docs/DESIGN.md) / [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)
