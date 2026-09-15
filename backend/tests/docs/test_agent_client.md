# test_agent_client.py

启动本机受控 gRPC 服务 → AgentClient 使用真实 protobuf 传输 → 验证字段及取消传播，不调用真实模型或 OCR。

- `test_grpc_resources_messages_and_original_call_cancellation`：验证独立 agent service 的资源引用、消息和选项映射，以及取消原 call 后服务端执行退出；资源准备由 `test_document_client.py` 覆盖。
- `test_grpc_failure_maps_to_agent_service_error`：验证 agent completion 上游 gRPC 错误映射为带诊断信息的 AgentServiceError。
