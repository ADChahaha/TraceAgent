# gRPC 服务入口测试

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

导入 main → 检查 gRPC server 工厂 → 后续通过真实本机 RPC 验证启动与生命周期。

- `test_entrypoint_provides_grpc_server`：入口提供异步 create_server，并移除旧 FastAPI app。
- `test_protocol_separates_document_resource_service`：验证文档准备 RPC 从 AgentService 拆到独立的 DocumentResourceService。
- `test_document_entrypoint_provides_separate_grpc_server`：验证 document service 有独立的 gRPC 服务工厂。
- `test_document_entrypoint_does_not_import_agent_route`：验证 document service 启动时不加载问答路由及其模型依赖。
- `test_health`：通过真实 RPC 读取标准健康状态。
- `test_agent_server_does_not_expose_document_rpc`：验证 agent 进程不会注册文档准备 RPC。
- `test_document_health`：通过独立 document service 读取标准健康状态。
- `test_capabilities_is_not_exposed`：协议、客户端和服务移除能力查询，同时移除无用消息类型，旧 RPC 路径返回 UNIMPLEMENTED。
- `test_blocking_preparation_keeps_control_rpcs_responsive`：单线程执行器忙于文档解析时，探活仍能响应。
- `test_oversized_request_returns_resource_exhausted`：超过配置消息上限的请求由 gRPC 拒绝，不进入业务处理。
- `test_cli_starts_server_and_health_command`：子进程启动真实服务，用 CLI 探活并确认退出码与状态文本。
- `test_document_cli_starts_server_and_health_command`：独立 document service 子进程启动、监听和探活成功。

移除独立取消 RPC 后，文档解析阻塞场景继续通过标准 Health 验证事件循环可响应。
