# Agent Loop

`CompletionRuntime._produce` 通过 async for 消费同文件 completion_runtime.py 的 `stream_completion_events`；后者包装 `run_qa_stream` 返回的模型消息和单个工具结果，最终由异步 consumer 输出带 seq 的字典，gRPC 接口转换为 protobuf 消息。

```text
manager 保存 completion_id → CompletionRuntime 映射
  → CompletionRuntime 只保存 workspace payload、messages、qa_model 和运行参数
  → astream 输出开始事件；stream_completion_events 输出 source_indexed(ok=true) 确认
  → run_qa_stream 用 workspace 调 build_tools，四个工具经 run_operation 启动一次性子进程
  → RunOptions 在构图时绑定工具执行器；文件读取与检索都在工具子进程内完成
  → messages.build_qa_messages(messages) 保留完整历史
  → loop.stream_qa_graph 调 graph.build_qa_graph；graph 绑定 model_invocation / executor，以 QaState 编译 agent/retry_wait/tools 图
  → 模型节点单次调用，messages 通道提供可见增量
  → 节点返回 AIMessage 或 ModelCallFailure；失败进入 retry_wait 指数退避再请求
  → loop 消费 messages/updates/custom，管理 message_id，将增量、完整结果和失败更新转换成类型化通知
  → completion_runtime 包装 started / delta / done / model_request.retrying / tool_started
  → 工具节点并行执行调用，on_result 经 custom 逐项输出 ToolMessage；完整返回值仅用于历史
  → completion_runtime 包装 tool_completed / tool_failed
  → producer 写 asyncio.Queue，astream 按 FIFO 编号，独自输出完成或失败
```

## 取消和失败

- 取消标志拒收新结果，取消 producer；Task 完成回调唤醒 consumer，清理后直接结束，不发取消终态。
- graph 在模型调用前后检查 should_stop，丢弃未发布的迟到响应；工具节点启动前检查停止信号，取消后不再请求下一轮模型。
- 工具普通异常和超时转为对应 ToolMessage；执行器整体异常转为整批失败结果。
- 同一配置最多请求五次，按以 0.5 秒起步、8 秒封顶并乘 0.75–1 随机系数的指数间隔；耗尽后 ModelFailed 转 completion.failed，取消不重试。每次尝试独立 message_id，局部失败文本不进入历史。
- 路由退出消费后只 await runtime.aclose，由 runtime 取消生产协程并关闭所持事件生成器；run_operation 会 kill 工具子进程，迟到结果不再写事件；runtime 通知 manager 移除注册项。问答结束保留文档资源。

管理 ID 不进入 graph；执行细节和取消锁语义见 [DESIGN.md](DESIGN.md)。

loop 组装输入、消费图流并转换输出；graph 负责节点和 Command 路由。RunOptions 仅配置工具共享超时，不再包含工具调用次数上限。

重试优先采用有效 retry-after-ms / Retry-After（秒数或 HTTP 日期，大于 0 且不超过 120 秒）；无效值回退到随机指数退避。retry_delay_ms 是本次实际等待时间的毫秒表示。
