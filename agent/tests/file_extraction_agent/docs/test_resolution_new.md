# test_resolution_new.py

这份测试覆盖 QA completion 的 resolution loop。resolution 不再围绕 `task_spec` 和字段写入，而是围绕 `tree/grep/read/inspect` 工具和用户可见的 evidence-bearing model message 推进。

实现链路：

```text
GraphState(messages + memory + HtmlDocument)
  -> build_resolution_messages 生成 QA system/human prompt
  -> build_resolution_messages 把 OpenAI 风格 messages 转成 LangChain chat/tool messages
  -> model.stream / model.invoke 产生 assistant content 和 tool call
  -> 同轮多 tool call 被截断为第一个
  -> _record_model_message 记录用户可见 content 和工具调用摘要
  -> ToolNode 执行 tree/grep/read/inspect
  -> 没有 tool call 时结束本轮 completion
```

## 测试函数

- `test_resolution_messages_describe_qa_investigation_not_field_extraction`：验证 prompt 说明 QA 调查流程和 evidence 规则，不再出现 `task_spec/write_field/submit_result` 字段抽取语义。
- `test_resolution_messages_preserve_openai_tool_history`：验证历史 assistant tool_calls 和 tool 结果会保留为真实 chat/tool message，而不是压成单一文本摘要。
- `test_resolution_graph_keeps_only_first_parallel_tool_call`：验证同轮多个 tool call 只执行第一个，保持可追溯的单步节奏。
- `test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 stream 调用能把 text chunk 和 tool call chunk 合并成带 content 和 tool_calls 的 `AIMessage`。
- `test_resolution_falls_back_from_responses_stream_to_chat_stream_then_invoke`：确认 Responses stream 失败后按顺序降级到 chat/completions stream 和非流 invoke。
- `test_resolution_records_text_from_responses_api_content_blocks`：确认 Responses API content block 列表会抽取 `type=text` 文本并写入 `model_message.content`。
- `test_resolution_records_model_message_content_and_tool_calls_without_reasoning`：确认 trace 只记录普通 assistant content 和工具摘要，不保存隐藏 reasoning content。
