# RPC 所有权测试

真实 gRPC 客户端发起问答 → 服务端执行替身事件流 → 取消或 deadline → 检查服务端 finally，资源准备和模型装配使用替身。

- `test_same_id_calls_are_independent`：相同请求 ID 的两个 RPC 可以并行，取消其中一个不影响另一个。
- `test_rpc_termination_cleans_awaiting_execution`：停止消费后取消、或 deadline 到期，都能清理等待中的执行。
- `test_removed_cancel_rpc_is_unimplemented`：协议移除独立取消方法，旧路径返回 UNIMPLEMENTED。
- `test_cancel_during_prepare_cleans_before_any_event`：首事件前取消也能清理正在等待的资源预检。
- `test_cancel_closes_generator_while_transport_is_sending`：发送大事件时客户端停止读取并取消，服务端关闭暂停在 yield 附近的生成器。

事件流模块引用同步为 turn_stream；仅重命名，不改变测试目标行为。
