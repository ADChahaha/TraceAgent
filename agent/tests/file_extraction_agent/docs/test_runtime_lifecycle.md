# Runtime 生命周期测试

用受控异步生成器驱动真实 runtime，验证内层只生产普通事件，外层根据 producer 结果决定完成或失败，主动取消直接结束流。

- `test_outer_stream_alone_emits_terminal`：普通事件返回或抛异常时，astream 独自生成开始和唯一终态，序号连续。
- `test_cancel_closes_without_terminal_and_waits_for_cleanup`：跨线程与重复取消不输出取消终态，等待异步 finally，移除回调只运行一次。
- `test_cancel_before_producer_starts_does_not_hang`：开始事件后立即取消、producer 尚未进入函数体也能结束。
- `test_inner_failure_raises_without_completion_event`：ModelFailed 转异常，内层不再生成 completion 事件。
- `test_runtime_aclose_owns_stream_cleanup`：调用方仅关闭 runtime，覆盖未启动、暂停消费时等待 producer 清理、关闭事件生成器及重复关闭只通知一次。
