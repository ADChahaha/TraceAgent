# test_manager.py

这份测试覆盖 `file_extraction_agent.manager` 的 QA completion 生命周期：`ActiveCompletion`
（单 completion 运行时，持有 state + model + 专属 queue + 锁，自行起 producer/consumer、
裁定终态、清理）与 `CompletionManager`（多 completion 注册表 + create/terminate/status
转发），以及模型配置读取。入口负责把 `completion_id`、`documents`、`messages` 和模型配置
组装成图输入，然后把图执行器产出的 SSE 原样向外迭代。

入口已经强类型化：`completion_manager.create(...)` 只接受
`documents: list[InputDocument]`、`messages: list[DocumentQaMessage]`、
`model_config: ModelConfig | None`、`run_options: RunOptions | None`，不再接受
`list[Any]` / `dict`，因此 dict / duck-typed 输入在边界即被拒收。

实现链路：

```text
completion_manager.create(...)（公开入口 = CompletionManager 单例）
  -> 装配：prepare_completion_state（校验 + materialize_tree + GraphState）
       -> build_resolution_model(model_config)
       -> ActiveCompletion(completion_id, state, model) 并注册
  -> ActiveCompletion.stream()：首次迭代启动 producer 线程，随后消费队列产 SSE
  -> producer(_produce) 运行 run_completion_graph_stream(state, model)，在 lock 下 commit 普通/终态事件
  -> terminate 在 lock 下置 cancel 状态：若当前没有运行中的 tool 批次，立即放 cancel sentinel
      唤醒 consumer；若正在执行 tool 批次，则标记 deferred cancel，等该批次跑完（或超时）后
      由 producer 以 completion.cancelled 收口，完整写入工具事件后再结束
  -> consumer 阻塞 queue.get；普通事件按 FIFO yield；cancel sentinel 前已提交事件不丢弃
  -> 收到 cancel sentinel / 终态事件时 close_once 收口；finally 清理 workspace（注册表移除在 manager）
```

## 测试函数

- `test_create_completion_stream_builds_completion_input_and_runs_graph`：用 fake model builder 和 fake stream graph 确认 `completion_manager.create(...)` 会传递 completion id、落盘文件树、messages 和 resolution model。
- `test_create_completion_stream_validates_input_before_iteration`：确认 completion 输入校验发生在返回 SSE iterator 前，route 层可以把业务入参错误稳定映射为 422。
- `test_create_completion_stream_registers_active_completion_before_iteration`：确认 active completion 会在返回 iterator 前注册，backend 立即调用 cancel 时不会因为流还没开始迭代而得到 `not_found`；早取消后 consumer 直接用 cancel sentinel 收口，不再启动 graph/provider producer。
- `test_create_completion_stream_cancel_does_not_wait_for_blocked_graph`：确认 graph/provider 卡住时，`completion_manager.terminate(...)` 会通过 runtime queue 的 cancel sentinel 主动唤醒 SSE consumer，consumer 立即输出 `completion.cancelled`，不等待 producer 继续产出或 queue timeout 轮询。
- `test_create_completion_stream_flushes_committed_events_before_cancel`：确认 cancel 前已经成功 commit 到 runtime queue 的普通 event 会先按 FIFO 发出，然后才输出 `completion.cancelled`；consumer 不能用 cancel flag 跳过旧 event。
- `test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed`：确认 cancel 与 producer 完成竞争时，同一个 completion 只会输出一个 terminal event。
- `test_terminate_defers_cancel_until_active_tool_batch_settles`：验证 cancel 到达正在执行的 tool 批次时会走 deferred cancel 路径——consumer 不会立即收口，而是等批次运行产生的工具事件（如 `tool_completed`）完整提交后再以 `completion.cancelled` 结束。
- `test_completion_manager_create_runs_graph_and_returns_sse`：确认 `CompletionManager.create(...)` 会把强类型入参落盘、构建状态、创建 resolution model，并返回可消费的 SSE 流。
- `test_completion_manager_create_registers_before_iteration_and_terminate_cancels`：确认 `create` 在返回 SSE 前先注册 runtime，`terminate` 能把 active completion 取消，早取消后 consumer 用 cancel sentinel 收口且不再启动 producer。
- `test_completion_manager_terminate_returns_not_found_for_unknown`：确认 `terminate` 对未知 completion id 返回 `not_found`。
- `test_completion_manager_get_status_returns_none_for_unknown`：确认 `get_status` 对未知 completion id 返回 `None`。
- `test_active_completion_owns_terminate_get_status_and_terminal_uniqueness`：确认 `ActiveCompletion` 直接持有 terminate/get_status，且 `close_once` 保证终态唯一（已关不能再关）。
- `test_prepare_completion_state_accepts_documents_and_append_only_messages`：确认输入准备函数保留 completion id、文档（落盘成 `DocumentFileTree`）和消息，图状态上不再存在 memory。
- `test_prepare_completion_state_rejects_memory_argument`：确认准备函数不再接收 `memory` 参数。
- `test_prepare_completion_state_rejects_missing_documents_or_messages`：确认 documents/messages 为空列表时抛 `ValueError`。
- `test_prepare_completion_state_rejects_document_without_filename_or_html`：确认 InputDocument 缺少文件名或 HTML 正文时抛 `ValueError`。
- `test_prepare_completion_state_requires_completion_id`：确认 completion id 为空时抛 `ValueError`。
- `test_normalize_model_config_loads_default_env_file`：确认模型配置能从 `.env` 中读取 base URL、key、`MODEL`、`MODEL_API_TRANSPORT`、采样参数、推理强度、重试次数和超时。
- `test_build_chat_model_builds_responses_transport_by_default`：确认默认只构造 Responses API 的 stream -> invoke 两级 attempt，未显式配置 `MODEL_REQUEST_TIMEOUT` 时默认 request timeout 为 8 秒。
- `test_build_chat_model_builds_chat_completions_transport_when_configured`：确认 `api_transport=chat_completions` 时只构造 chat/completions 的 stream -> invoke 两级 attempt。
- `test_build_chat_model_rejects_unknown_transport`：确认 `MODEL_API_TRANSPORT` 只允许 `responses` 或 `chat_completions`，不支持 `auto`。
- `test_normalize_model_config_rejects_untyped_dict_input`：确认 `normalize_model_config` 拒绝未定型 dict 输入，模型配置边界也走强类型。
