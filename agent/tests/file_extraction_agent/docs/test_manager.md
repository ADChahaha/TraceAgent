# test_manager.py

执行链路：manager 委托工具层预检资源路径和索引 → 注册独立 completion_runtime.CompletionRuntime → 接收模型消息和逐项工具结果 → 锁内队列提交 → consumer 分配 seq 并返回事件字典 → 运行时通过 on_close 移除注册表，保留资源。

测试消费 manager.create(...) 返回的运行时：迭代其 stream()，断连仅调用运行时 close；测试覆盖未迭代就关闭（runtime.close）、断连唤醒和 ID 复用后的隔离。

取消唤醒 consumer 并取消 producer；等待协程清理后关闭，不补齐工具结果。事件内容断言归一化掉 seq 后比较，独立完整流测试验证序号连续及终态唯一。事件转换只提取可见文本，异常与超时结果保留原始调用 ID。

## 测试函数

- `test_disconnect_before_iteration_does_not_start_producer`：注册回调后立即断开，首次迭代不创建 producer，仍清理注册项。
- `test_unstarted_stream_close_removes_registration`：预检注册后尚未迭代就关闭，runtime.close() 仍移除注册项且不启动执行。
- `test_disconnect_wakes_consumer_and_stops_producer`：断连唤醒阻塞 consumer 并设置 producer 停止信号；旧回调不取消复用相同 ID 的新运行时。
- `test_runtime_yields_event_objects_with_sequence`：运行时逐条输出带连续 seq 的事件字典，保留正文换行并完成收尾；不输出 SSE 文本。
- `test_manager_keeps_id_outside_runtime_and_cleans_only_matching_entry`：CompletionRuntime 构造函数和对象不接收或保存 ID；ID 仅保存在注册表和 manager 的流清理闭包；一轮结束只清理对应注册项，另一轮仍可按 ID 取消并清理。
- `test_completion_runtime_streams_without_manager`：独立构造 completion_runtime.py 的运行时，验证无需注册表也能输出有序事件并唯一收尾。
- `test_stream_numbers_messages_and_terminal_once`：完成、失败流连续编号且只有一个终态；取消直接结束，无 completion ID。
- `test_startup_events_only_acknowledge_without_reading_documents`：启动通知只返回状态和 ok，不遍历目录、读取文档或附带资源内容。
- `test_runtime_cancel_interrupts_real_tools_and_skips_next_model`：真实 LangGraph 并行同名工具执行中取消，中断未完成调用后关闭；不再请求模型，并保留资源目录。
- `test_manager_wraps_messages_and_pairs_same_name_calls`：completion_runtime 将 AIMessage/ToolMessage 包装为模型、调度和结果事件，同名工具按 call ID 保留各自参数及失败状态。
- `test_graph_keeps_events_as_objects_until_stream_boundary`：图执行器返回事件字典，仅包装索引和 Agent 事件，不生成生命周期事件。
- `test_stream_preserves_runtime_failure_with_special_characters`：运行时异常含换行、制表符、引号和反斜杠时，仍输出一个保留原始异常文本的失败事件。
- `test_stream_preserves_terminal_words_in_data`：正文含终态字样时仍输出后续真实终态。
- `test_create_completion_stream_builds_completion_input_and_runs_graph`：用 fake model builder 和 fake stream graph 确认 `completion_manager.create(...)` 只传递资源路径、messages 和 qa model，completion ID 留在运行时管理层。
- `test_create_completion_stream_validates_input_before_iteration`：确认 completion 输入校验发生在返回事件 iterator 前，route 层可以把业务入参错误稳定映射为传输层参数错误。
- `test_create_completion_stream_registers_completion_runtime_before_iteration`：确认 active completion 会在返回 iterator 前注册，backend 立即调用 cancel 时不会因为流还没开始迭代而得到 `not_found`；早取消后 consumer 直接结束，不再启动 graph/provider producer。
- `test_create_completion_stream_cancel_does_not_wait_for_blocked_graph`：取消 producer 打断阻塞等待，Task 完成回调唤醒 consumer，等待清理后直接结束。
- `test_create_completion_stream_discards_queued_events_after_cancel`：取消后丢弃尚未交付的队列事件，不输出取消终态。
- `test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed`：取消与完成竞争时，不重复输出终态；取消先被观察到则直接关闭。
- `test_terminate_interrupts_active_tool_batch`：取消中断活动工具等待，无需释放工具 gate 即可关闭，无迟到工具结果。
- `test_should_stop_is_wired_to_cancel_requested`：验证 `_produce` 把 `should_stop=lambda: self.cancel_requested` 注入到 `stream_completion_events`，使取消信号能在图执行外部被观测——cancel 前 should_stop 为 False，terminate 后变为 True。
- `test_completion_manager_create_runs_graph_and_returns_events`：确认 `CompletionManager.create(...)` 会校验路径、传递消息、创建 qa model，并返回可消费的事件流。
- `test_completion_manager_create_registers_before_iteration_and_terminate_cancels`：确认 `create` 在返回事件流前先注册 runtime，`terminate` 能把 active completion 取消，早取消后 consumer 直接结束且不再启动 producer。
- `test_completion_manager_terminate_returns_not_found_for_unknown`：确认 `terminate` 对未知 completion id 返回 `not_found`。
- `test_completion_manager_get_status_returns_none_for_unknown`：确认 `get_status` 对未知 completion id 返回 `None`。
- `test_runtime_cancel_flag_is_idempotent`：仅保存 cancel_requested，重复取消幂等，不保存 status、closed 或 terminal_committed。
- `test_normalize_model_config_loads_default_env_file`：确认模型配置能从 `.env` 中读取 base URL、key、`MODEL`、`MODEL_API_TRANSPORT`、采样参数、推理强度、重试次数和超时。
- `test_build_chat_model_builds_responses_transport_by_default`：默认以固定配置使用 Responses 流式调用，默认请求超时 8 秒。
- `test_build_chat_model_builds_chat_completions_transport_when_configured`：显式配置 chat_completions 时，构造对应的固定流式调用配置。
- `test_build_chat_model_rejects_unknown_transport`：确认 `MODEL_API_TRANSPORT` 只允许 `responses` 或 `chat_completions`，不支持 `auto`。
- `test_normalize_model_config_rejects_untyped_dict_input`：确认 `normalize_model_config` 拒绝未定型 dict 输入，模型配置边界也走强类型。
- `test_qa_records_text_from_responses_api_content_blocks`：只提取 Responses 内容块中的可见文本。
- `test_qa_records_terminal_stop_message_as_final_answer`：合法终止消息标为最终回答。
- `test_qa_records_model_message_content_and_tool_calls_without_reasoning`：保留工具调用和可见文本，不泄露推理。
事件替身和事件断言均不携带 completion ID；取消/状态接口仍按 ID 定位运行时。运行时测试通过真实 resource_path 进入，保留取消竞态、FIFO、终态唯一和消息包装覆盖。原每轮建树/清理测试由资源准备和损坏资源测试替代。

模型装配替身注入 manager；事件生成和图执行替身注入 completion_runtime。现有取消竞态、FIFO、注册表移除和终态测试覆盖拆分后的协作。

测试使用协程与异步迭代器驱动实际 Agent 链路；模型替身提供 astream/ainvoke，取消等待使用事件循环。

断连测试验证生产协程的 finally 观察停止信号，提前断连不会创建生产协程。
模型构造替身检查 SDK 的 `timeout` 参数（`request_timeout` 的别名），默认请求超时仍为 8 秒。

模型配置测试改为单一配置、单一流式调用，不再生成 invoke fallback；完整消息事件改为 model_message.done，并携带 message_id。

模型装配对象重命名为 ConfiguredChatModel，明确只保存一个固定调用配置。

取消测试现在验证活动工具无需配齐结果即可终止，不输出迟到工具结果，也不启动下一次模型请求。

本轮契约调整：内层只输出普通 Agent 事件；完成/失败由 astream 唯一出口生成，取消直接结束且不输出 cancelled。对应测试改用 producer 结果或外层流验证，保留配对、重试和资源清理覆盖。

关闭入口统一为 close：未启动时直接移除注册项，已启动时取消 producer 并由流 finally 清理；断连测试同时覆盖重复关闭与 ID 复用隔离。
