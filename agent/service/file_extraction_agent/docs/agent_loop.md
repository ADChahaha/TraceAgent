# Agent Loop

`CompletionRuntime._produce` 通过 async for 消费同文件 completion_runtime.py 的 `stream_completion_events`；后者包装 `run_qa_stream` 返回的模型消息和工具批次，最终由异步 consumer 输出带 seq 的字典，gRPC 接口转换为 protobuf 消息。

```text
manager 保存 completion_id → CompletionRuntime 映射
  → CompletionRuntime 只保存 resource_path、messages、qa_model 和运行参数
  → stream_completion_events 输出无 completion ID 的开始事件与 source_indexed(ok=true) 确认
  → run_qa_stream 调 open_workspace(resource_path)，build_tools 绑定工具上下文
  → RunOptions 在构图时绑定工具执行器，文件访问与 embedding 缓存由工具层持有
  → messages.build_qa_messages(messages) 保留完整历史
  → loop 调 graph.stream_qa_graph；graph 绑定 model_invocation / executor，以 MessagesState 编译并运行图
  → 模型节点返回 AIMessage
  → completion_runtime 包装 model_message / tool_started
  → 工具节点并行执行整批调用，返回 list[ToolMessage]
  → completion_runtime 包装 tool_completed / tool_failed
  → runtime 锁内入队并唤醒 asyncio.Event，astream 协程按 FIFO 分配 seq 并输出字典
```

## 取消和失败

- 无活动工具批次时，取消 sentinel 立即唤醒 consumer；已有批次则先配齐结果。
- graph 在模型调用前后检查 should_stop，丢弃未发布的迟到响应；已发布工具批次配齐结果后停止，不再请求下一轮模型。
- 工具普通异常和超时转为对应 ToolMessage；执行器整体异常转为整批失败结果。
- 模型调用失败耗尽尝试后向 completion_runtime 抛异常，输出 tool_failed（tool=qa）及 completion.failed；取消优先以 cancelled 收口。
- 关闭事件流时先 disconnect 再 await aclose 事件生成器并取消生产协程，工具内迟到线程结果不再写事件；runtime 通知 manager 移除注册项。问答结束保留文档资源。

管理 ID 不进入 graph；执行细节和取消锁语义见 [DESIGN.md](DESIGN.md)。

loop 只组装 Agent 输入、转发输出和关闭内层生成器；图节点、Command 路由、更新转换、递归保护及图流关闭全部归 graph。RunOptions 仅配置工具共享超时，不再包含工具调用次数上限。
