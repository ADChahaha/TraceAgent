# 页面恢复与 SSE 事件协议

返回 [Backend API](../API.md)。

## `GET /resume?session_id=...`

- manager 捕获当前轮副本和已存在轮次列表并登记订阅，请求侧读取 `chat_messages` 与 `chat_turns` 渲染历史轮；查询期间新事件入队。
- 先合并发送首帧快照，再持续消费增量；不会创建新 turn，也不会重新调用 agent。
- 不提供 `after_seq`、`Last-Event-ID` 或 SSE `id` 协议；前端保存 `session_id`，每次收到快照时整份替换已有会话展示。

## SSE 帧格式

```text
event: session.snapshot
data: {"session_id":"s1","state":{"status":"running","active_turn_id":"t1","resources":[],"turns":[{"id":"t1","status":"in_progress","items":[],"error":null}]}}

event: session.event
data: {"turn_id":"t1","type":"model_message.delta","payload":{"message_id":"m1","delta":"你好"}}
```

## 增量合并与连接生命周期

- `items` 包含用户消息、模型尝试、工具与重试状态。消费端按消息或调用 ID 更新；`model_message.done` 的完整正文替换累计 `delta`，不同模型尝试不可拼接。
- 增量事件只包含 `turn_id`、`type`、`payload`，不暴露内部序号。常见类型为 `turn.started`、`model_message.started`/`delta`/`done`、`tool_started`/`completed`/`failed`、`turn.completed`/`failed`/`cancelled`。
- 默认 15 秒无事件时发送注释心跳。
- 流在首帧捕获的活跃轮终结后关闭；无活跃轮时仅发送一次快照。正常终态无需重连，意外断开后重新 `GET /resume`。
- 多页面订阅相互独立，慢页面队列溢出仅断开自身连接。
