# test_runtime_lifecycle

普通事件或执行异常 → 外层统一编号并生成终态；内层仅报告模型失败。

- `test_outer_stream_alone_emits_terminal`：正常与失败路径各输出唯一终态，序号连续。
- `test_inner_failure_raises_without_completion_event`：模型失败在内层抛异常，不重复产生 completion 终态。

执行入口改为直接消费 stream_completion(...) 异步生成器，不创建运行时对象。
