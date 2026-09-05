# test_loop.py

执行链路：资源路径和输入消息 → prompt/历史转换 → 绑定工具 → 正式 LangGraph agent/tools 循环 → 原样 yield AIMessage/ToolMessage；运行异常向外抛出，图内无事件或取消缓冲。

工具并行提交并共享超时期限；按原始调用 ID 返回消息。超时失败先返回，迟到线程不能修改已返回消息。模型调用覆盖 stream/invoke 降级、响应终止信号校验和退避；manager 负责事件格式与最终回答标记。

## 测试函数

- `test_qa_stream_yields_only_original_messages`：同一正式循环返回原始模型消息和匹配的工具回复，没有 outcome 包装或重复最终消息。
- `test_graph_state_has_no_event_or_runtime_buffers`：执行上下文不保存事件、action、序号、事件锁及取消批次状态。
- `test_qa_requires_tool_binding_before_invoking_model`：缺少 `bind_tools` 的模型在调用前报错，不能通过旧字典协议执行备用循环。
- `test_tool_timeout_emits_one_matching_result_and_discards_late_success`：验证超时只返回一个带调用 ID 的失败 ToolMessage，迟到成功不改写消息。
- `test_tool_exception_is_reported_consistently_without_timeout`：普通异常保留真实错误，并与模型收到的结果一致。
- `test_qa_messages_describe_qa_investigation_not_field_extraction`：验证 prompt 说明 QA 调查流程和 evidence 规则（真实路径块链接），要求过程消息用可读 label、最终回答用数字 label、citation 紧跟被支撑句子，不汇总成一个总 `Sources` 区；同时验证不再出现 `task_spec/write_field/submit_result` 字段抽取语义，system prompt 不再接收 memory context。
- `test_qa_prompt_allows_direct_answers_without_forced_document_search`：验证 prompt 明确允许身份、能力和已有上下文可回答的问题直接回答，只有用户询问文档内容、要求证据或上下文不清楚时才使用文档工具；同时确认 prompt 使用 `ls / grep / read` 命名，避免把结构浏览工具描述成递归 `tree`，并避免用 `Show your thought process` 诱导隐藏推理。
- `test_qa_messages_preserve_openai_tool_history`：验证历史 assistant tool_calls 和 tool 结果会保留为真实 chat/tool message；最新用户消息仍是模型看到的最后一条 human 消息。
- `test_qa_graph_preserves_parallel_tool_calls`：验证 provider 同轮返回多个 tool call 时，qa graph 会保留完整 tool_calls 摘要，并行执行这些工具，按原调用顺序返回结果。
- `test_parallel_tool_executor_runs_all_calls_concurrently`：直接验证 `_execute_tools_parallel` 会把同一批多个 tool_calls 并发执行（用一个 gate 证明两个工具同时进入执行而非串行等待），且各自返回带匹配 `tool_call_id` 的 `ToolMessage`。
- `test_parallel_tool_executor_times_out_slow_call`：验证慢工具在超过 `tool_execution_timeout` 后返回带 `tool execution timeout` 结果的 `ToolMessage`，不会无限阻塞整个批次。
- `test_qa_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 stream 调用能把 text chunk 和 tool call chunk 合并成带 content 和 tool_calls 的 `AIMessage`。
- `test_qa_falls_back_from_stream_to_invoke_within_configured_transport`：确认一个已配置 transport 内 stream 失败后会降级到同 transport 的非流 invoke，不承担跨 Responses/chat-completions 自动切换。
- `test_qa_uses_ethernet_backoff_between_failed_provider_attempts`：确认 provider attempt 失败后，会按 `[0, 2^k - 1]` slot 的随机指数退避等待，再进入下一 attempt。
- `test_qa_stops_after_provider_attempt_limit`：确认同一轮 provider 调用最多尝试五次，避免无限重试或长期占用 producer。
- `test_qa_retries_transport_when_provider_stop_signal_requires_missing_tool_calls`：验证 provider 给出 `finish_reason=tool_calls` 但 LangChain 消息里没有实际 `tool_calls` 时，会把该响应视为不完整并切换到下一个 transport。
- `test_qa_accepts_terminal_stop_message_without_tool_calls`：验证 `finish_reason=stop` 这类 terminal stop signal 仍会作为自然文本终态处理。
- `test_qa_rejects_plan_only_message_without_terminal_stop_signal`：验证只有计划性文本、没有工具调用、也没有 terminal stop signal 的模型响应不能被当成完成结果。

执行输入改为资源路径；`test_qa_stream_yields_only_original_messages` 验证模型消息和整批工具结果。工具与 prompt 测试仅构造文件树，不依赖 manager 初始化状态。
