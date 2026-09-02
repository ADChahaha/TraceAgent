# test_processor.py

这份测试覆盖 `file_extraction_agent.manager` 的 QA completion 生命周期管理（`CompletionManager`）和模型配置读取。入口负责把 `completion_id`、`documents`、`messages` 和模型配置组装成图输入，然后把图执行器产出的 SSE 原样向外迭代。

入口已经强类型化：`create_completion_stream` 只接受
`documents: list[InputDocument]`、`messages: list[DocumentQaMessage]`、
`model_config: ModelConfig | None`、`run_options: RunOptions | None`，不再接受
`list[Any]` / `dict`，因此 dict / duck-typed 输入在边界即被拒收。

实现链路：

```text
create_completion_stream(...)
  -> prepare_completion_state(...)
       -> 校验 completion_id、documents、messages、run_options（失败抛 ValueError）
       -> materialize_tree 落盘 DocumentFileTree
       -> build_graph_state -> GraphState
  -> build_resolution_model(model_config)
  -> 注册 ActiveCompletion
  -> ActiveCompletion 持有本 completion 专属 runtime queue
  -> producer 运行 run_completion_graph_stream(state, resolution_model)
  -> producer 在 runtime lock 下把普通 event 或 terminal event commit 到 queue
  -> cancel_completion 在同一把 runtime lock 下设置 cancel 状态并放入 cancel sentinel
  -> consumer 阻塞等待 runtime queue，不做 timeout 轮询
  -> 普通 event 按 FIFO yield；cancel sentinel 前已提交的普通 event 不会被丢弃
  -> consumer 收到 cancel sentinel 后通过 close_once 输出 completion.cancelled
```

## 测试函数

- `test_create_completion_stream_builds_completion_input_and_runs_graph`：用 fake model builder 和 fake stream graph 确认 `create_completion_stream(...)` 会传递 completion id、documents、messages 和 resolution model。
- `test_create_completion_stream_validates_input_before_iteration`：确认 completion 输入校验发生在返回 SSE iterator 前，route 层可以把业务入参错误稳定映射为 422。
- `test_create_completion_stream_registers_active_completion_before_iteration`：确认 active completion 会在返回 iterator 前注册，backend 立即调用 cancel 时不会因为流还没开始迭代而得到 `not_found`；早取消后 consumer 直接用 cancel sentinel 收口，不再启动 graph/provider producer。
- `test_create_completion_stream_cancel_does_not_wait_for_blocked_graph`：确认 graph/provider 卡住时，`cancel_completion(...)` 会通过 runtime queue 的 cancel sentinel 主动唤醒 SSE consumer，consumer 立即输出 `completion.cancelled`，不等待 producer 继续产出或 queue timeout 轮询。
- `test_create_completion_stream_flushes_committed_events_before_cancel`：确认 cancel 前已经成功 commit 到 runtime queue 的普通 event 会先按 FIFO 发出，然后才输出 `completion.cancelled`；consumer 不能用 cancel flag 跳过旧 event。
- `test_create_completion_stream_emits_only_one_terminal_event_when_cancel_races_completed`：确认 cancel 与 producer 完成竞争时，同一个 completion 只会输出一个 terminal event。
- `test_completion_manager_create_runs_graph_and_returns_sse`：确认 `CompletionManager.create(...)` 会把强类型入参落盘、构建状态、创建 resolution model，并返回可消费的 SSE 流。
- `test_completion_manager_create_registers_before_iteration_and_terminate_cancels`：确认 `create` 在返回 SSE 前先注册 runtime，`terminate` 能把 active completion 取消，早取消后 consumer 用 cancel sentinel 收口且不再启动 producer。
- `test_completion_manager_terminate_returns_not_found_for_unknown`：确认 `terminate` 对未知 completion id 返回 `not_found`。
- `test_completion_manager_get_status_returns_none_for_unknown`：确认 `get_status` 对未知 completion id 返回 `None`。
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
