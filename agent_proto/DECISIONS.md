# agent_proto 关键决策

归属 [共享 agent 协议](docs/DESIGN.md)，记录 gRPC 协议包的长期契约取舍。

## 1. 协议拆分为独立 `traceagent-protocol` wheel

- 决定：`agent_proto` 与 `agent`、`document_service`、`backend` 同级独立打包，仅依赖 `grpcio` 与 `protobuf`，不把生成绑定复制进业务包。
- 原因：让 `backend` 和各服务共享唯一 gRPC 契约且不拉入彼此业务依赖（例如 `torch`、`langgraph`）。
- 排除：把 proto 定义与生成代码耦合在 `agent` 包内部再由其他服务跨包导入。

## 2. 按服务拆分 RPC，取消走原 `call.cancel()`

- 决定：仅保留 `DocumentResourceService.PrepareResources` 与 `AgentService.ChatCompletion`（及资源读接口），探活统一用标准 gRPC Health；取消通过原 `ChatCompletion` gRPC `call.cancel()` 传播，`completion_id` 只作格式校验，不提供 `CancelCompletion`、`GetCompletion`、`GetCapabilities`。
- 原因：避免服务侧维护全局活动 completion 注册表和跨请求状态，让每次调用无状态且易于取消收口。
- 排除：保留独立取消 RPC 和按 `completion_id` 路由的活动任务表。

## 3. 已删字段保留 `reserved`，资源只传 `resource_path`

- 决定：删除的字段编号与名称（如 `RunOptions.max_tool_calls` 编号 1、`PrepareResourcesResponse.documents` 编号 2）保留为 `reserved`；资源准备响应只返回指向对象存储归档的 `resource_path`，不再内联返回 `Document` HTML。
- 原因：防止后续字段复用造成线上反序列化冲突，同时避免大文档 HTML 经由 RPC 载荷重复传输。
- 排除：直接复用已删字段编号或在 RPC 响应中内联文档正文。
