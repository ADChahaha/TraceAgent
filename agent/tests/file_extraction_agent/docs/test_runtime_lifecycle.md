# test_runtime_lifecycle

core 增量、异常或 ModelFailed → 路由直接编码和编号 → 验证正常/失败路径只有一个终态。

- `test_outer_stream_alone_emits_terminal`：正常与失败路径各输出唯一终态，序号连续。
- `test_model_failure_becomes_single_failed_completion`：core 的 ModelFailed 转成唯一失败终态并保留错误文本。
