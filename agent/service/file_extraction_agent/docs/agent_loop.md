# Agent Loop

`ActiveCompletion._produce` 在后台消费 manager 的 `stream_completion_events`；后者包装 `run_qa_stream` 返回的模型消息和工具批次，最终由 consumer 编码 SSE。

```text
ActiveCompletion 保存 completion_id、resource_path、messages、qa_model
  → stream_completion_events 输出无 completion ID 的开始事件与 source_indexed(ok=true) 确认
  → run_qa_stream 根据 resource_path 调 build_graph_state，仅初始化执行输入
  → build_tools 创建工具上下文，文件访问与 embedding 缓存由工具层持有
  → build_qa_messages 保留完整历史，build_qa_graph 绑定工具并编译图
  → 模型节点返回 AIMessage
  → manager 包装 model_message / tool_started
  → 工具节点并行执行整批调用，返回 list[ToolMessage]
  → manager 包装 tool_completed / tool_failed
  → runtime 锁内入队，consumer 按 FIFO 分配 seq 并输出 SSE
```

## 取消和失败

- 无活动工具批次时，取消 sentinel 立即唤醒 consumer；已有批次则先配齐结果。
- `run_qa_stream` 在工具批次返回后检查 should_stop，不再请求下一轮模型。
- 工具普通异常和超时转为对应 ToolMessage；执行器整体异常转为整批失败结果。
- 模型调用失败耗尽尝试后向 manager 抛异常，输出 tool_failed（tool=qa）及 completion.failed；取消优先以 cancelled 收口。
- 关闭外层流时关闭内层生成器，迟到线程结果不再写事件。问答结束保留文档资源。

管理 ID 不进入 graph；执行细节和取消锁语义见 [DESIGN.md](DESIGN.md)。
