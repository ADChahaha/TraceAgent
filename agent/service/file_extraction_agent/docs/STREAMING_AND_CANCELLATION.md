# 流式输出与取消

模型增量和单个工具结果到达后立即输出；图只在节点完成后保存完整历史。
取消通过 Task.cancel 传播到模型或工具 await，等待协程 finally 清理后结束；工具子进程会被 kill，迟到结果不输出。

```text
ChatCompletion(resource_path, messages)
  → 路由校验资源、装配模型并直接消费 stream_completion
  → loop.run_qa_stream 初始化工作区、工具和模型消息
  → graph.build_qa_graph 编译 agent / retry_wait / tools
  → loop 消费 graph.astream(messages, updates, custom)
      ├─ messages：可见模型 chunk → MessageStarted / MessageDelta
      ├─ updates：模型完整结果或失败 → AIMessage / ModelRetry / ModelFailed
      └─ custom：单个工具结果 → ToolMessage
  → stream_completion_events 包装业务事件 → stream_completion 编号 → gRPC
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
  -> 为每项 create_task，await tool.ainvoke
  -> 工具经 worker_client.run_operation 启动一次性子进程并等待 stdout
  -> asyncio.wait(FIRST_COMPLETED) 等待下一项完成或共享 deadline
  -> 完成项归一化成 ToolMessage，立即调用 on_result
  -> graph writer 写 custom → loop → tool_completed / tool_failed
  -> 全部完成后按原调用顺序返回完整历史，tools 节点更新 messages
  -> graph 再调用下一轮模型
```

普通异常和超时转换为失败结果；超时或取消会停止 run_operation 并 kill 未完成的工具子进程，
不等待其自然结束。loop 不再次输出 tools updates，避免重复事件。结果通过 tool_call_id 配对，
交付顺序可以不同于调用顺序。

## 取消

```text
客户端取消原 ChatCompletion call
  → grpc.aio 取消 handler，取消沿 await 传播
  → aclosing 关闭 stream_completion、run_qa_stream 和图流
  → executor 取消未完成工具 Task，worker_client finally kill 子进程
  → 执行退出，不发送取消终态
```

没有运行时类、注册表、独立 producer 或事件队列。暂停消费由 gRPC 流控处理；停止消费后客户端应取消原 call。取消不撤回已经交付的事件，backend 负责禁止旧轮迟到写入。call.cancel 返回不代表远端清理完成；同步阻塞工作可能延迟取消。
