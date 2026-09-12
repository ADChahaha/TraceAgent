# test_rpc_owned_execution

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

真实 gRPC 客户端 → 路由消费 core 替身 → 客户端取消、deadline 或发送背压 → 验证服务端 finally 和 RPC 隔离。

- `test_same_id_calls_are_independent`：相同请求 ID 的两个 RPC 可以并行，取消其中一个不影响另一个。
- `test_rpc_termination_cleans_awaiting_execution`：停止消费后取消、或 deadline 到期，都能清理等待中的执行。
- `test_removed_cancel_rpc_is_unimplemented`：协议移除独立取消方法，旧路径返回 UNIMPLEMENTED。
- `test_cancel_during_prepare_cleans_before_any_event`：首事件前取消也能清理正在等待的资源预检。
- `test_cancel_closes_generator_while_transport_is_sending`：发送大事件时客户端停止读取并取消，服务端关闭暂停在 yield 附近的生成器。
