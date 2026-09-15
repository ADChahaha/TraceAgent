# RPC 测试夹具

`rpc_server_factory` 和 `document_rpc_server_factory` 分别在独立线程的事件循环启动 agent/document gRPC 服务 → 同步测试客户端发送 RPC → 通知循环停止并等待关闭。

`rpc_channel`/`rpc` 提供 AgentServiceStub，`document_rpc_channel`/`document_rpc` 提供 DocumentResourceServiceStub。两个工厂都允许测试独立设置阻塞工作线程数和消息上限。
