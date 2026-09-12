# test_runtime_lifecycle

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

core 增量、异常或 ModelFailed → application 编号 → 路由编码函数 编码 → 验证正常/失败路径只有一个终态。

- `test_outer_stream_alone_emits_terminal`：正常与失败路径各输出唯一终态，序号连续。
- `test_model_failure_becomes_single_failed_completion`：core 的 ModelFailed 转成唯一失败终态并保留错误文本。
