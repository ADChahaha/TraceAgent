# 请求内执行链

消费 stream_completion 流 → 直接推进普通事件生成器 → 取消当前 Task → 等待内层 finally 完成。

- `test_execution_stays_in_consuming_task`：业务执行与消费者位于同一 Task，暂停消费不会由独立 producer 提前生产事件。
- `test_consumer_cancellation_waits_for_inner_cleanup`：取消传播到内层等待，清理完成前消费者不退出，且不补发终态。

执行入口改为直接消费 stream_completion(...) 异步生成器，不创建运行时对象。
