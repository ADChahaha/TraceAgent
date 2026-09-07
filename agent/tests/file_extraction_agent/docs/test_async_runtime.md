# 异步运行时测试

真实 CompletionManager 创建流 → 异步等待生产线程的事件 → 检查顺序、终态和注册表释放。

- `test_async_stream_preserves_events_and_cleanup`：完成、失败和取消均按序输出字典事件，消费结束释放注册项。
- `test_waiting_streams_leave_executor_free_and_cancel_cleanly`：四条流等待时，单线程执行器仍可处理工作；业务取消立即确认，协程取消和关闭均清理注册项。

事件替身使用异步生成器，与生产协程一致；同步 RPC 客户端的跨线程测试信号通过 await 等待。
