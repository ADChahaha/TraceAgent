# 图状态、重试退避与循环职责

返回 [文档问答执行设计](../DESIGN.md)。

## 执行输入与 `QaState`

- `QaState` 继承 `MessagesState`，增加 `model_attempt`、`model_failure`、`retry_delay_seconds`。
- 只有校验通过的完整消息进入 `messages`；失败尝试的部分文本不进入历史。workspace payload、运行参数和工具运行参数均保存在图状态之外。
- `run_qa_stream` 为 Agent 核心接口：校验非空消息和 workspace -> `build_tools` 为四个工具绑定同一 payload -> `build_qa_messages` 转换完整历史 -> `stream_qa_graph` 执行图并转换输出。关闭流时通过 `aclosing` 关闭内层生成器并等待原生图流 `aclose`。
- `RunOptions` 只保留 `tool_execution_timeout`（默认 60 秒），已删除 `max_tool_calls`；LangGraph 递归保护仍为 10000，由 `graph.py` 内部配置。

## `graph.py` 与重试退避

- `graph.py` 绑定固定模型并编译 `agent`、`retry_wait`、`tools` 三个节点。
- `agent` 每次只调用一次 `model_invocation`；`ModelCallFailure` 通过 `Command` 更新状态，未达上限路由至 `retry_wait`，否则结束。同一逻辑模型调用最多 5 次请求，成功后计数归零，工具完成后的下一次模型调用重新计数。无效工具 ID 抛 `ValueError`，不发完整消息、不执行工具。
- 失败结果保留 `retry_after_seconds`：优先从响应头解析 `retry-after-ms`，其次 `Retry-After` 秒数或 HTTP 日期；仅接受有限且 `> 0`、`<= 120` 秒的值，直接采用不叠加抖动。
- 无有效头时回退指数退避：以 0.5 秒起步、8 秒封顶并乘 `0.75-1.0` 随机系数。等待时间只计算一次，事件 `retry_delay_ms` 使用同一值换算毫秒。

## 原生流转换与异常出口

- `loop.stream_qa_graph` 使用 `graph.astream(stream_mode=["messages", "updates", "custom"])`：`messages` 提供原生 chunk，`updates` 提供节点结束结果，`custom` 提供单个 `ToolMessage`；loop 不重复发布 `tools` 的 `updates`。
- 仅读取 `agent` 节点可见文本，过滤隐藏推理与工具参数。每次实际请求首次观察到输出时分配独立 `message_id` 发 `MessageStarted`，随后发 `MessageDelta`，完成时发带同一 ID 的完整 `AIMessage`。无回调的注入模型仅在完成时输出正文。
- 失败更新转为 `ModelRetry` 或 `ModelFailed`：`ModelRetry` 在退避结束前发出，携带失败 `message_id`、下一次 `attempt`、`max_attempts=5`、`retry_delay_ms`、`error`；下一次请求用新 ID。
- `application` 将 `ModelFailed` 转异常，由 `stream_execution` 统一输出 `completion.failed`。动态值 JSON 校验失败或 protobuf 编码失败（经 `athrow` 回传）均走同一失败终态出口并复用未发送序号。`CancelledError` 在模型与退避中直接传播，不转为失败或重试。

## 循环六文件职责拆分

| 文件 | 核心职责 |
| --- | --- |
| `loop.py` | 校验输入、初始化工具与消息、调 `build_qa_graph`、消费 `graph.astream` 合并增量与更新并关闭图流 |
| `graph.py` | 绑定依赖、定义 `QaState` 及 `agent`/`retry_wait`/`tools` 节点与路由，取消沿 await 传播 |
| `contracts.py` | 声明模型/工具 Protocol、`BoundModel`、`AgentOutput` 和 JSON 类型；动态工具结果以 `object` 接入 |
| `messages.py` | 完整历史转系统提示与模型输入；响应终止信号校验（不完整抛 `RuntimeError`）；JSON 归一化 |
| `model_invocation.py` | 单次 `astream`/`ainvoke` 聚合校验，返回 `AIMessage` 或 `ModelCallFailure`，`finally` 关闭响应流 |
| `executor.py` | 并发 `create_task(ainvoke)`，按共享 deadline `FIRST_COMPLETED` 经 `on_result` 即时发布并按原序回写历史 |
