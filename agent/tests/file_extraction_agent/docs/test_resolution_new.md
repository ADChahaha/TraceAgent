# test_resolution_new.py

这份测试覆盖 QA completion 的 resolution loop。resolution 不再围绕 `task_spec` 和字段写入，而是围绕 `tree/grep/read/inspect` 工具和用户可见的 evidence-bearing model message 推进。

实现链路：

```text
GraphState(messages + HtmlDocument)
  -> build_resolution_messages 生成 QA system prompt
  -> prompt 要求过程消息可以 inline cite，最终回答正文不放 evidence link，末尾追加 Sources 区
  -> build_resolution_messages 把 OpenAI 风格 messages 原样转成 LangChain chat/tool messages
  -> 最新真实用户消息保持为最后一条 HumanMessage，不追加额外运行指令
  -> model.stream / model.invoke 产生 assistant content 和 tool call
  -> _invoke_model_message 校验 provider stop signal 与 tool_calls 是否一致
  -> provider attempt 失败时按 Ethernet 式随机指数退避后进入下一 attempt
  -> 同轮多个 tool call 保留在同一条 AIMessage 中并交给 ToolNode 执行
  -> _record_model_message 记录用户可见 content、工具调用摘要和 is_final/stop_signal
  -> ToolNode 执行 tree/grep/read/inspect
  -> terminal stop signal 且没有 tool call 时结束本轮 completion
```

## 测试函数

- `test_resolution_messages_describe_qa_investigation_not_field_extraction`：验证 prompt 说明 QA 调查流程和 evidence 规则，要求最终回答使用末尾 Sources 区而不是正文 inline evidence link；同时验证不再出现 `task_spec/write_field/submit_result` 字段抽取语义，system prompt 不再接收 memory context，真实用户消息后面不会再追加强制调查文档的 `HumanMessage`。
- `test_resolution_prompt_allows_direct_answers_without_forced_document_search`：验证 prompt 明确允许身份、能力和已有上下文可回答的问题直接回答，只有用户询问文档内容、要求证据或上下文不清楚时才使用文档工具；同时避免用 `Show your thought process` 这类说法诱导模型输出隐藏推理。
- `test_resolution_messages_preserve_openai_tool_history`：验证历史 assistant tool_calls 和 tool 结果会保留为真实 chat/tool message，而不是压成单一文本摘要；最新用户消息仍是模型看到的最后一条 human 消息。
- `test_resolution_graph_preserves_parallel_tool_calls`：验证 provider 同轮返回多个 tool call 时，resolution graph 会保留完整 tool_calls 摘要，并按顺序执行这些工具。
- `test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 stream 调用能把 text chunk 和 tool call chunk 合并成带 content 和 tool_calls 的 `AIMessage`。
- `test_resolution_falls_back_from_stream_to_invoke_within_configured_transport`：确认一个已配置 transport 内 stream 失败后会降级到同 transport 的非流 invoke，不承担跨 Responses/chat-completions 自动切换。
- `test_resolution_uses_ethernet_backoff_between_failed_provider_attempts`：确认 provider attempt 失败后，会按 `[0, 2^k - 1]` slot 的随机指数退避等待，再进入下一 attempt。
- `test_resolution_stops_after_provider_attempt_limit`：确认同一轮 provider 调用最多尝试五次，避免无限重试或长期占用 producer。
- `test_resolution_records_text_from_responses_api_content_blocks`：确认 Responses API content block 列表会抽取 `type=text` 文本并写入 `model_message.content`。
- `test_resolution_retries_transport_when_provider_stop_signal_requires_missing_tool_calls`：验证 provider 给出 `finish_reason=tool_calls` 但 LangChain 消息里没有实际 `tool_calls` 时，会把该响应视为不完整并切换到下一个 transport，避免把计划性文本误判为最终回答。
- `test_resolution_accepts_terminal_stop_message_without_tool_calls`：验证 `finish_reason=stop` 这类 terminal stop signal 仍会作为自然文本终态处理。
- `test_resolution_records_terminal_stop_message_as_final_answer`：验证没有 tool call 且带 terminal stop signal 的 `model_message` 会记录 `is_final=true` 和归一化 `stop_signal`，供 backend 保存最终 assistant message。
- `test_resolution_rejects_plan_only_message_without_terminal_stop_signal`：验证只有计划性文本、没有工具调用、也没有 terminal stop signal 的模型响应不能被当成完成结果。
- `test_resolution_records_model_message_content_and_tool_calls_without_reasoning`：确认 trace 只记录普通 assistant content、工具摘要和 `is_final=false`，不保存隐藏 reasoning content。
