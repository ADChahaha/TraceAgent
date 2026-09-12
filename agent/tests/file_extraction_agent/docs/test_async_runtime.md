# test_async_runtime

多个路由事件流等待 core 替身 → 取消消费 Task → 验证阻塞执行器仍可用且各流独立清理。

- `test_waiting_streams_leave_executor_free_and_cancel_cleanly`：等待流不占执行器，取消一条不影响其他流，最终全部清理。
