# test_rpc_execution_chain

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

调用方迭代路由 protobuf 流 → 驱动 core 替身 → 暂停或取消 → 验证无后台生产及等待内层清理。

- `test_execution_stays_in_consuming_task`：业务执行与消费者位于同一 Task，暂停消费不会由独立 producer 提前生产事件。
- `test_consumer_cancellation_waits_for_inner_cleanup`：取消传播到内层等待，清理完成前消费者不退出，且不补发终态。
