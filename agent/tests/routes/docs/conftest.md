# RPC 测试夹具

`rpc_server_factory` 在独立线程的事件循环启动真实 grpc.aio 服务 → 同步测试客户端发送 RPC → 通知循环停止并等待关闭。

`rpc_channel` 提供默认配置的连接；`rpc` 提供 AgentServiceStub。工厂允许测试独立设置阻塞工作线程数和消息上限。
