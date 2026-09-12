# protobuf 事件适配测试

业务依赖注入 application 层；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

将类型化的模型、工具与重试输出注入 application → 消费 `stream_completion` → 直接检查 protobuf 字段、事件顺序和生成器清理。

- `test_stream_returns_protobuf_from_first_event`：第一条启动事件就是 `CompletionEvent`，无需字典转换。
- `test_typed_outputs_preserve_wire_events_and_json`：验证增量、重试、工具、最终回答和终态顺序，保留消息 ID、大整数、null、特殊字符及显式 false。
- `test_tool_result_fallback_and_failure_status`：验证无 artifact 时的 JSON/文本回退，以及工具失败判定。
- `test_failure_closes_core_and_emits_one_terminal`：模型失败通知和普通异常均关闭内层流，只产生一个失败终态。
- `test_encoding_failure_closes_core_and_keeps_sequence`：非法 JSON 数值编码失败时关闭内层流，失败终态序号仍连续。
- `test_dynamic_result_serializes_once`：嵌套结果中的大整数、null 与中文保持不变，整个业务流到 protobuf 输出只对该结果执行一次 JSON 序列化。
