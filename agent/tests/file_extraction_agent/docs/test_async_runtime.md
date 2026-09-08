# 异步运行时测试

真实 CompletionManager 创建流 → 异步等待生产协程的事件 → 检查顺序、终态和注册表释放。

- `test_async_stream_preserves_events_and_cleanup`：完成、失败和取消均按序输出字典事件，消费结束释放注册项。
- `test_waiting_streams_leave_executor_free_and_cancel_cleanly`：四条流等待时，单线程执行器仍可处理工作；业务取消立即确认，协程取消和关闭均清理注册项。

事件替身使用异步生成器，与生产协程一致；同步 RPC 客户端的跨线程测试信号通过 await 等待。测试通过 manager.create(...).stream() 消费单一事件生成器，并在结束后 await 生成器 aclose 触发运行时收尾。

生命周期更新：内层替身不生成 completion 事件，外层统一开始/完成/失败；业务取消的 RPC 确认不变，原流直接结束，不输出 completion.cancelled。
