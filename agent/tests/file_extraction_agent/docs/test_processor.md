# test_processor.py

这份测试覆盖 `file_extraction_agent.processor` 的 QA completion 入口和模型配置读取。入口负责把 `completion_id`、`documents`、`messages`、`memory` 和模型配置组装成图输入，然后把图执行器产出的 SSE 原样向外迭代。

实现链路：

```text
create_completion_stream(...)
  -> build_completion_input(...)
  -> build_resolution_model(model_config)
  -> 注册 ActiveCompletion
  -> ActiveCompletion 持有本 completion 专属 runtime queue
  -> producer 运行 run_completion_graph_stream(completion_input, resolution_model)
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
- `test_normalize_model_config_loads_default_env_file`：确认模型配置能从 `.env` 中读取 base URL、key、模型名、采样参数、推理强度、重试次数和超时。
- `test_build_chat_model_builds_responses_stream_then_chat_fallbacks`：确认 resolution chat model 会按 `responses_stream -> chat_completions_stream -> responses_invoke -> chat_completions_invoke` 构造四级 fallback，默认优先 Responses API 和 stream，失败后再退到 chat/completions 与非流调用；未显式配置 `MODEL_REQUEST_TIMEOUT` 时默认 request timeout 为 8 秒。
- `test_normalize_model_config_rejects_unknown_model_fields`：确认模型配置拒绝未知字段，避免旧 broad/resolution 多阶段配置重新进入 QA completion 入口。
