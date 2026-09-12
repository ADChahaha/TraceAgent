# test_agent_client.py

启动本机受控 gRPC 服务 → AgentClient 使用真实 protobuf 传输 → 验证字段及取消传播，不调用真实模型或 OCR。

- `test_grpc_resources_messages_and_original_call_cancellation`：传输带正文的最小 DOCX，验证资源引用、消息和选项映射，取消原 call 后服务端执行退出。
- `test_grpc_failure_maps_to_agent_service_error`：上游 gRPC 错误映射为带诊断信息的 AgentServiceError。
