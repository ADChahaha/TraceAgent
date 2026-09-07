# gRPC 服务入口测试

导入 main → 检查 gRPC server 工厂 → 后续通过真实本机 RPC 验证启动与生命周期。

- `test_entrypoint_provides_grpc_server`：入口提供 create_server，并移除旧 FastAPI app。
- `test_health_and_capabilities`：通过真实 RPC 读取标准健康状态和支持的文件类型。
- `test_busy_work_is_rejected_and_cancel_stays_available`：长任务达到容量后快速拒绝新工作，保留取消 RPC 的处理能力。
- `test_oversized_request_returns_resource_exhausted`：超过配置消息上限的请求由 gRPC 拒绝，不进入业务处理。
- `test_cli_starts_server_and_health_command`：子进程启动真实服务，用 CLI 探活并确认退出码与状态文本。
