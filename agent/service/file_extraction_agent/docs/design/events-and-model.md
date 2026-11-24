# 模型装配、事件批次与正文归一化

本页属 [文档问答执行设计](../DESIGN.md)，记录模型配置、文本提取规则以及模型/工具事件批次交付契约。

## 模型装配与文本归一化

```text
ModelConfig 或环境变量
  -> 校验 provider 与 api_transport
  -> _chat_model_class 延迟加载标准 ChatOpenAI
  -> use_responses_api 选择 Responses 或 Chat Completions，SDK max_retries 固定为 0
  -> ConfiguredChatModel 保存单个 provider 与 use_stream，bind_tools 返回 BoundModel
  -> model_invocation 按 use_stream 调用并校验完整消息
```

- 生产配置固定 `streaming=True`，不自动降级，不再维护多模型候选列表。
- SDK 内层 `max_retries` 固定为 0，避免与图内 5 次重试相乘；旧配置字段暂保留解析，不再控制 SDK 重试。
- 已删除 `openai_models.py` 以及 DeepSeek 专用 `reasoning_content` 保存/回传和 `thinking` 参数注入；`reasoning_effort` 等通用参数按标准 SDK 传入。
- 工具契约仅支持 `ainvoke`，不再声明同步工具。取消仅依赖 Task 与生成器关闭，不再传递 `should_stop` 回调。
- `messages.visible_text` 统一处理增量与完整消息：字符串直接返回；列表只保留字符串与 `text` 块字符串，忽略隐藏推理、非文本块及无效 text 值。

## 模型与工具事件批次

每条 gRPC 流绑定本轮请求，事件不重复携带 completion ID；`completion_id` 仅保留请求格式校验。`tool_call_id` 及模型 `tool_calls` 内的 ID 保留用于调用与结果配对。

```text
模型节点调用 model_invocation._invoke_model_message
  -> 校验响应完整性与工具 ID 唯一性 -> yield AIMessage
  -> application 输出 model_message.done；有调用则输出 tool_started

工具节点调用 executor._execute_tools_parallel
  -> asyncio.create_task 并发执行整批工具协程，按共享 deadline 与原序收集成功/异常/超时结果
  -> 每项 ToolMessage 携带 tool_call_id、name、additional_kwargs.tool_args、artifact、status
  -> 单项完成立即经 on_result -> graph custom -> loop yield ToolMessage
  -> application 输出 tool_completed / tool_failed
  -> 整批完成后才将完整结果按原调用顺序写入图状态，供下一轮模型使用
```

## 交付与终态不变式

- 对外模型事件为 `model_message.started`、`model_message.delta`、`model_message.done`，重试事件为 `model_request.retrying`。消费端按 `message_id` 追加 `delta`，收到 `done` 时以 `done.content` 确认或替换而不可再次追加；重试后新 ID 开启新正文。`done` 仅表示单条消息完成，整轮以 `completion.*` 终态为准。
- 事件包装不维护 pending 配对字典。工具节点按调用 ID 保留已发布的完整 `ToolMessage`；执行器异常时仅为未发布项补失败结果再按原序写入历史，已发布结果不覆盖、不重复输出。
- 合法 terminal stop signal、无 `tool_calls` 且可见正文非空时标记 `is_final=true`。无工具调用的空白或仅隐藏推理响应由 `messages` 校验拒绝，进入 5 次重试流程，不写入历史也不发布 `model_message.done`；工具调用仍允许空正文。
- 图更新不重复输出历史消息或最后一条回答；普通模型失败在图内退避，第 5 次耗尽后通过 `ModelFailed` 以 `completion.failed` 收口。
