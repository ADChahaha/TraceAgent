# 异步测试辅助

固定输出或业务执行流 → 异步消费/协议编码；等待事件时提供可超时结果。

- `async_items`：把固定序列变成异步流替身。
- `wait_event`：等待异步事件，超时返回 false。
- `wire_stream`：组合真实 service.stream_execution 与 protobuf 编码器；提前关闭时关闭业务流。

输出适配器位于 `routes/file_extraction_agent.py`；编码错误回传业务流处理终态。
