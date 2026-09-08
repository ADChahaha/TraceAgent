# 流式输出与取消

模型增量和单个工具结果到达后立即输出；图只在节点完成后保存完整历史。
取消通过 Task.cancel 传播到模型或工具 await，等待协程 finally 清理后结束；线程中的计算自行结束，迟到结果不输出。

```text
ChatCompletion(resource_path, messages)
  → manager 校验资源、装配模型并注册 CompletionRuntime
  → loop.run_qa_stream 初始化工作区、工具和模型消息
  → graph.build_qa_graph 编译 agent / retry_wait / tools
  → loop 消费 graph.astream(messages, updates, custom)
      ├─ messages：可见模型 chunk → MessageStarted / MessageDelta
      ├─ updates：模型完整结果或失败 → AIMessage / ModelRetry / ModelFailed
      └─ custom：单个工具结果 → ToolMessage
  → stream_completion_events 包装业务事件 → runtime 队列 → seq → gRPC
```

## 模型与重试

model_invocation 单次调用固定模型，聚合并校验完整 AIMessage；普通失败返回 ModelCallFailure，取消异常继续传播。
graph 在同一配置下最多请求五次，失败经 updates 通知后进入 retry_wait。
优先采用有效 retry-after-ms / Retry-After（秒数或 HTTP 日期，有限且大于 0、不超过 120 秒）；
否则等待 min(0.5 × 2^(失败次数−1), 8) × (1 − 0.25 × random()) 秒。
事件 retry_delay_ms 与实际等待使用同一次计算值；取消模型或退避不重试。

每次尝试使用独立 message_id，输出 model_message.started / delta / done；失败尝试的部分正文不写入图历史。
第五次失败输出 completion.failed。done 正文用于确认或替换，消费端不能再次追加。

## 工具即时结果

```text
executor 接收 tool_calls、tools、共享 timeout 和 on_result
  → 为每项 create_task，优先 ainvoke，同步工具使用 to_thread
  → asyncio.wait(FIRST_COMPLETED) 等待下一项完成或共享 deadline
  → 完成项归一化成 ToolMessage，立即调用 on_result
  → graph writer 写 custom → loop → tool_completed / tool_failed
  → 全部完成后按原调用顺序返回完整历史，tools 节点更新 messages
  → graph 再调用下一轮模型
```

普通异常和超时转换为失败结果；超时取消未完成 Task 并等待清理。
loop 不再次输出 tools updates，避免重复事件。结果通过 tool_call_id 配对，交付顺序可以不同于调用顺序。

## 取消

```text
CancelCompletion(id)
  → runtime 锁内标记 cancelling，拒收后续结果；立即返回状态
  → 入队取消 sentinel，call_soon_threadsafe 安排 producer.cancel
  → 图中断模型等待或工具节点等待
  → executor finally 取消未完成工具 Task，gather 等待协程清理
  → 工具 await 抛 CancelledError，执行 finally 后退出
  → consumer 发出已提交的 FIFO 事件，等待 producer 清理后输出唯一 completion.cancelled
  → 关闭流并按对象身份移除注册项
```

不等待工具正常计算结束，不补造 TOOL_ABORTED 或其他工具结果。已提交结果保留，取消后的迟到结果拒收。
重复取消不再次中断正在进行的清理。完成先提交时保留原终态，注册项移除后返回 not_found。
断连/deadline 同样取消生产协程，但连接不可用时不保证交付终态。

Task.cancel 是协作式取消；工具必须传播 CancelledError，finally 的异步清理仍可能等待。
to_thread 中的函数无法安全强杀，继续执行后其返回值不再进入工具协程；写文件等副作用不会撤销。
本实现不引入独立进程、强制线程终止或固定清理宽限期。

## 消费端与历史

agent 不负责持久化跨轮历史。backend/前端需按 message_id 展示增量，按 tool_call_id 接收逐项结果。
取消可能留下有 tool_calls 但缺少结果的消息；消费端必须处理这种中断状态，不能直接当作完整工具历史回传模型。
backend/前端的历史与展示适配不在本次实现范围内。

覆盖测试包括：模型实时增量、同配置重试、工具快慢并发、取消执行 finally、线程未释放时 RPC 已终止、FIFO 和唯一终态。
实际模块边界见 [DESIGN.md](DESIGN.md)，对外字段见 [API.md](../../../docs/API.md)。
