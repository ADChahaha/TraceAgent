# backend/routes 关键决策

归属 [Backend 设计](../docs/DESIGN.md) 与 [Backend API](../docs/API.md)，记录 HTTP 路由与流式传输协议的长期取舍。

## 1. 实时流采用单向 SSE 配合独立 HTTP 控制端点，活跃轮由终态事件驱动关闭

- 决定：服务端向客户端推送轮次进展统一采用单向 SSE（`text/event-stream`，首帧输出 `session.snapshot`，随后增量推送 `session.event`），取消、文件增删与只读查询走独立 HTTP 端点；活跃轮的 SSE 流仅在收到目标轮次终态事件（`turn.completed`、`turn.failed`、`turn.cancelled`）或订阅关闭时退出，空闲等待期间按 `sse_heartbeat_seconds` 发送注释心跳保活。
- 原因：问答执行以服务端单向推送为主，单向 SSE 加独立 HTTP 端点比客户端持续轮询更高效，也比双向长连接 WebSocket 更轻量；由目标终态驱动关流可避免模型或工具等待间隙队列短暂为空时提前断流。
- 排除：用客户端高频轮询替代流推送；引入双向 WebSocket 承载控制与流事件；以订阅队列为空作为活跃轮关流条件。
