# 系统架构与服务索引（L1）

本页汇总 TraceAgent 各服务边界与一手设计与接口文档的二级路由（顶层入口见 [memory.md](../../memory.md)）。

## 页面路由

| 查找需求 | 目标页（L2） | 核心覆盖 |
| --- | --- | --- |
| 7 个顶层包职责、默认端口、部署边界与设计文档入口 | [services.md](services.md) | `agent_proto` / `storage` / `shared` / `document_service` / `agent` / `backend` / `frontend` 边界与文档路由 |

## 一手设计与接口入口

- 顶层架构与原则：[ARCHITECTURE.md](../../ARCHITECTURE.md) / [design-docs](../../docs/design-docs/index.md) / [core-beliefs](../../docs/design-docs/core-beliefs.md)
- 产品规格与总览：[product-specs](../../docs/product-specs/index.md) / [README.md](../../README.md)
- 协议与存储：[agent_proto](../../agent_proto/docs/DESIGN.md) / [storage](../../storage/docs/DESIGN.md) / [shared](../../shared/docs/DESIGN.md)
- 文档与问答服务：[document_service](../../document_service/docs/DESIGN.md) / [agent](../../agent/docs/DESIGN.md) / [agent API](../../agent/docs/API.md)
- 编排与前端：[backend](../../backend/docs/DESIGN.md) / [backend API](../../backend/docs/API.md) / [frontend](../../frontend/docs/DESIGN.md)
