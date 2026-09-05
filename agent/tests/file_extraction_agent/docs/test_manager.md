# test_manager.py

执行链路：校验资源路径 → 构建 runtime → 接收模型消息和工具结果批次 → 锁内队列提交 → consumer 分配 seq 并编码 SSE → 移除注册表，保留资源。

取消批次按已提交模型事件中的调用 ID 跟踪；工具结果先配齐再关闭。旧 SSE 内容断言归一化掉 seq 后比较，独立完整流测试验证序号连续及终态唯一。事件转换只提取可见文本，异常与超时结果保留原始调用 ID。

## 测试函数

- `test_stream_numbers_messages_and_terminal_once`：完成、失败、取消三种完整输出流均连续编号且仅有一个终态；问答执行失败的阶段名为 qa。
- `test_runtime_cancel_drains_real_graph_batch_and_skips_next_model`：真实 LangGraph 并行同名工具执行中取消，等待匹配结果后关闭；不再请求模型，并保留资源目录。
- `test_manager_wraps_messages_and_pairs_same_name_calls`：manager 将 AIMessage/ToolMessage 包装为模型、调度和结果事件，同名工具按 call ID 保留各自参数及失败状态。
- `test_graph_keeps_events_as_objects_until_stream_boundary`：图执行器返回事件字典，开始、索引、终态顺序不变。
- `test_stream_encodes_runtime_failure_with_special_characters`：运行时异常含换行、制表符、引号和反斜杠时，仍输出一个可解析的 SSE 失败帧。
- `test_stream_preserves_terminal_words_in_data`：正文含终态字样时仍输出后续真实终态。
- `test_terminal_status_reads_only_event_type`：三种 completion 终态都只按字典的 type 取状态。
- `test_terminal_detection_requires_exact_event_type`：正文、status 和前缀相似名称不会结束流。
- `test_create_completion_stream_builds_completion_input_and_runs_graph`：用 fake model builder 和 fake stream graph 确认 `completion_manager.create(...)` 会传递 completion id、资源路径、messages 和 qa model。
- `test_create_completion_stream_validates_input_before_iteration`：确认 completion 输入校验发生在返回 SSE iterator 前，route 层可以把业务入参错误稳定映射为 422。
- `test_create_completion_stream_registers_active_completion_before_iteration`：确认 active completion 会在返回 iterator 前注册，backend 立即调用 cancel 时不会因为流还没开始迭代而得到 `not_found`；早取消后 consumer 直接用 cancel sentinel 收口，不再启动 graph/provider producer。
- `test_create_completion_stream_cancel_does_not_wait_for_blocked_graph`：确认 graph/provider 卡住时，`completion_manager.terminate(...)` 会通过 runtime queue 的 cancel sentinel 主动唤醒 SSE consumer，consumer 立即输出 `completion.cancelled`，不等待 producer 继续产出或 queue timeout 轮询。
- `test_create_completion_stream_flushes_committed_events_before_cancel`：确认 cancel 前已经成功 commit 到 runtime queue 的普通 event 会先按 FIFO 发出，然后才输出 `completion.cancelled`；consumer 不能用 cancel flag 跳过旧 event。
- `test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed`：确认 cancel 与 producer 完成竞争时，同一个 completion 只会输出一个 terminal event。
- `test_terminate_defers_cancel_until_active_tool_batch_settles`：验证 cancel 到达正在执行的 tool 批次时会走 deferred cancel 路径——consumer 不会立即收口，而是等批次运行产生的工具事件（如 `tool_completed`）完整提交后再以 `completion.cancelled` 结束。
- `test_should_stop_is_wired_to_cancel_requested`：验证 `_produce` 把 `should_stop=lambda: self.cancel_requested` 注入到 `stream_completion_events`，使取消信号能在图执行外部被观测——cancel 前 should_stop 为 False，terminate 后变为 True。
- `test_completion_manager_create_runs_graph_and_returns_sse`：确认 `CompletionManager.create(...)` 会校验路径、传递消息、创建 qa model，并返回可消费的 SSE 流。
- `test_completion_manager_create_registers_before_iteration_and_terminate_cancels`：确认 `create` 在返回 SSE 前先注册 runtime，`terminate` 能把 active completion 取消，早取消后 consumer 用 cancel sentinel 收口且不再启动 producer。
- `test_completion_manager_terminate_returns_not_found_for_unknown`：确认 `terminate` 对未知 completion id 返回 `not_found`。
- `test_completion_manager_get_status_returns_none_for_unknown`：确认 `get_status` 对未知 completion id 返回 `None`。
- `test_active_completion_owns_terminate_get_status_and_terminal_uniqueness`：确认 `ActiveCompletion` 直接持有 terminate/get_status，且 `close_once` 保证终态唯一（已关不能再关）。
- `test_normalize_model_config_loads_default_env_file`：确认模型配置能从 `.env` 中读取 base URL、key、`MODEL`、`MODEL_API_TRANSPORT`、采样参数、推理强度、重试次数和超时。
- `test_build_chat_model_builds_responses_transport_by_default`：确认默认只构造 Responses API 的 stream -> invoke 两级 attempt，未显式配置 `MODEL_REQUEST_TIMEOUT` 时默认 request timeout 为 8 秒。
- `test_build_chat_model_builds_chat_completions_transport_when_configured`：确认 `api_transport=chat_completions` 时只构造 chat/completions 的 stream -> invoke 两级 attempt。
- `test_build_chat_model_rejects_unknown_transport`：确认 `MODEL_API_TRANSPORT` 只允许 `responses` 或 `chat_completions`，不支持 `auto`。
- `test_normalize_model_config_rejects_untyped_dict_input`：确认 `normalize_model_config` 拒绝未定型 dict 输入，模型配置边界也走强类型。
- `test_qa_records_text_from_responses_api_content_blocks`：只提取 Responses 内容块中的可见文本。
- `test_qa_records_terminal_stop_message_as_final_answer`：合法终止消息标为最终回答。
- `test_qa_records_model_message_content_and_tool_calls_without_reasoning`：保留工具调用和可见文本，不泄露推理。
运行时测试通过真实 resource_path 进入，保留取消竞态、FIFO、终态唯一和消息包装覆盖。原每轮建树/清理测试由资源准备和损坏资源测试替代。
