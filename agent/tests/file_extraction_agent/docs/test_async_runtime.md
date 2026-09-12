# test_async_runtime

四条流同时等待 → 验证阻塞执行器可用 → 分别取消并检查清理。

- `test_waiting_streams_leave_executor_free_and_cancel_cleanly`：等待流不占执行器，取消一条不影响其他流，最终全部清理。

执行入口改为直接消费 stream_completion(...) 异步生成器，不创建运行时对象。

事件流模块引用同步为 turn_stream；仅重命名，不改变测试目标行为。
