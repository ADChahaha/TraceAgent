# RPC 测试夹具

create_server → 绑定本机随机端口 → 建立 channel → 提供 AgentServiceStub → 测试后关闭 channel 与 server。消息收发上限与服务默认值一致。

- `rpc_channel`：提供真实 gRPC 连接，等待就绪并确保回收。
- `rpc`：提供生成的 agent 客户端。
