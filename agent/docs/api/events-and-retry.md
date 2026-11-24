# 问答事件流与重试规则

本页属 [Agent gRPC API](../API.md)，定义 `CompletionEvent` 事件类型、重试退避算法和消费端状态合并契约。

## 事件类型表

路由直接消费 core 的类型化输出，逐条构造并 yield `CompletionEvent`，gRPC 自行分帧，不经过字典事件层。`seq` 从 1 连续递增，每条流绑定一个 completion，不重复携带 `completion_id`。

| `type` | 内容 |
| --- | --- |
| `completion.created` | 开始执行，`status=in_progress` |
| `source_indexed` | 启动确认，`result_json` 为 `{"ok":true}`，不返回文档树 |
| `model_message.started` | `message_id`；每次实际请求独立，在首次输出被观察到时发送 |
| `model_message.delta` | `message_id`、`delta`；新增可见文本 |
| `model_message.done` | `message_id`、`content`、`tool_calls`、`tool_call_count`、`is_final`、可选 `stop_signal` |
| `model_request.retrying` | `message_id`（失败尝试）、`attempt`（下一次，2-5）、`max_attempts=5`、`retry_delay_ms`、`error` |
| `tool_started` | `tool`、`tool_call_id`、`args_json` |
| `tool_completed` / `tool_failed` | 对应调用的 `args_json`、`result_json` |
| `completion.completed` / `completion.failed` | 正常或失败终态、`status`；失败携带 `error_message`。主动取消直接结束流，不发终态 |

## 字段编码规则

- `args_json`、`result_json` 及 `ToolCall.args_json` 用 JSON 字符串保留动态结构、大整数和 null；客户端用 `json.loads` 解码。
- 其余固定字段使用 protobuf 类型，可选字段可用 `HasField` 判断。
- 最终回答由 `is_final=true` 标记；工具调用 ID 用于配对，模型引用 `documents` 下的真实 Markdown key 路径。

## 重试与退避

- 每次逻辑模型调用最多尝试 5 次，始终使用同一配置。
- 优先采用响应头中有效的 `retry-after-ms` / `Retry-After`（秒数或 HTTP 日期，大于 0 且不超过 120 秒）；无效值回退到随机指数退避。
- 指数退避公式：`min(0.5 * 2^(failures - 1), 8) * (1 - 0.25 * random())` 秒；4 次等待约 375-500、750-1000、1500-2000、3000-4000 ms。`retry_delay_ms` 是本次实际等待时间的毫秒值。
- 重试通知在等待结束前发出；第 5 次失败以 `completion.failed` 结束。
- SDK 内层重试关闭；旧 `model_config.max_retries` / `MODEL_MAX_RETRIES` 暂保留解析但不再控制请求次数。

## 消费端合并契约

- 按 `message_id` 追加 `delta`；收到 `done` 时用 `done.content` 替换/确认完整正文，不再追加。
- 收到 `retrying` 时将关联旧消息标记失败；下一次 `started` 使用新 ID，正文不能拼接。
- 失败尝试的部分文本只供展示，不作为完整 assistant 历史回传。取消或失败可能没有 `done`。
- 旧 `model_message` 消费端必须升级到 `started`/`delta`/`done` 事件模型。
