# agent_proto 关键决策

归属 [共享 agent 协议](docs/DESIGN.md)，记录 gRPC 协议包的长期契约取舍。

## 1. 协议拆分为独立 `traceagent-protocol` wheel

- 决定：`agent_proto` 与 `agent`、`document_service`、`backend` 同级独立打包，仅依赖 `grpcio` 与 `protobuf`，不把生成绑定复制进业务包。
- 原因：让 `backend` 和各服务共享唯一 gRPC 契约且不拉入彼此业务依赖（例如 `torch`、`langgraph`）。
- 排除：把 proto 定义与生成代码耦合在 `agent` 包内部再由其他服务跨包导入。

## 2. 按服务拆分 RPC，取消走原 `call.cancel()`

- 决定：仅保留 `DocumentResourceService.PrepareResources`、`DocumentResourceService.ReadBlocks`、`AgentService.ChatCompletion` 与无状态标题总结 `AgentService.GenerateTitle`，探活统一用标准 gRPC Health；取消通过原 `ChatCompletion` gRPC `call.cancel()` 传播，`completion_id` 只作格式校验，不提供 `CancelCompletion`、`GetCompletion`、`GetCapabilities`。
- 原因：避免服务侧维护全局活动 completion 注册表和跨请求状态，让每次调用无状态且易于取消收口；同时将标题模型推理放在 `agent` 侧，维持 `backend` 不直接调用模型的分层边界。
- 排除：保留独立取消 RPC 和按 `completion_id` 路由的活动任务表；或在 `backend` 直接引入模型 SDK 生成会话标题。

## 3. 已删字段保留 `reserved`，资源只传 `resource_path`

- 决定：删除的字段编号与名称（`RunOptions.max_tool_calls` 编号 1、`PrepareResourcesResponse.documents` 编号 2，以及 `ChatCompletionRequest` 的 `documents`、`metadata`、`memory`、`task_spec`）均保留为 `reserved`；资源准备响应只返回指向对象存储归档的 `resource_path`，不再内联返回 `Document` HTML。
- 原因：防止后续字段复用造成线上反序列化冲突或无意重新引入已废弃的旧架构字段，同时避免大文档 HTML 经由 RPC 载荷重复传输。
- 排除：直接复用已删字段编号和字段名，或在 RPC 响应中内联文档正文。

## 4. 现阶段两服务共用单份 `agent.proto` 与单一协议 wheel

- 决定：`agent` 与 `document_service` 已拆分为独立进程与代码包，但现阶段刻意共用同一份 `agent_proto/agent.proto` 与同一个 `traceagent-protocol` wheel，服务实现侧各自只注册对应 Servicer。
- 原因：两服务共享 `ResourceRef` 等核心消息契约，保持单一 proto 文件与协议包可避免多协议包版本对齐与额外构建维护成本。
- 排除：在服务拆分初期过早拆分为多份 `.proto` 文件或多个独立协议 wheel。
