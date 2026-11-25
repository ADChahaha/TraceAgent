# backend/routes 关键决策

归属 [Backend 设计](../docs/DESIGN.md) 与 [Backend API](../docs/API.md)，记录 HTTP 路由与流式传输协议的长期取舍。

## 1. 实时流采用单向 SSE 配合独立 HTTP 控制端点，活跃轮由终态事件驱动关闭

- 决定：服务端向客户端推送轮次进展统一采用单向 SSE（`text/event-stream`，首帧输出 `session.snapshot`，随后增量推送 `session.event`），取消、文件增删与只读查询走独立 HTTP 端点；活跃轮的 SSE 流仅在收到目标轮次终态事件（`turn.completed`、`turn.failed`、`turn.cancelled`）或订阅关闭时退出，空闲等待期间按 `sse_heartbeat_seconds` 发送注释心跳保活。
- 原因：问答执行以服务端单向推送为主，单向 SSE 加独立 HTTP 端点比客户端持续轮询更高效，也比双向长连接 WebSocket 更轻量；由目标终态驱动关流可避免模型或工具等待间隙队列短暂为空时提前断流。
- 排除：用客户端高频轮询替代流推送；引入双向 WebSocket 承载控制与流事件；以订阅队列为空作为活跃轮关流条件。

## 2. 对外 HTTP 与轮次错误经 `user_errors.py` 脱敏分类，技术细节仅留服务端日志

- 决定：在 [backend/services/user_errors.py](../services/user_errors.py) 集中维护错误分类与英文用户态文案映射，由 [errors.py](errors.py)、[chat.py](chat.py) 与 [turn_runtime.py](../services/turn_runtime.py) 在对外出口调用；原始 gRPC 异常、上游报错与堆栈先写入服务端日志，HTTP `detail` 与 SSE/快照 `turn.error` 只返回清晰、具体、可操作且不含底层实现细节的英文提示（`AgentClient`/`DocumentResourceClient` 内部异常原文保持不变）。
- 原因：前端工作台面向最终用户，直接透出 `gRPC`、`ipv4:127.0.0.1:8002`、Python 依赖名或 Pydantic 堆栈既影响可读性又暴露内部实现；同时服务端排障仍需要完整技术信息。
- 排除：把内部 gRPC/Python 异常原文直接返回给浏览器；在底层 gRPC client 中抹掉原始错误文本导致排障失明；仅靠前端正则掩盖而允许后端 HTTP/SSE 继续泄露内部细节。

## 3. HTTP 路由层禁止跳过 `services` 直连 `crud` 或数据库模块

- 决定：所有 HTTP 路由（如 `GET /chat/sessions`）统一经 `backend/services/` 用例入口（如 `session_catalog.list_recent_sessions`）访问持久化数据，禁止 `backend/routes/*` 直接 import `backend.crud`、`backend.core.db` 或 `backend.models`，并由 [check_architecture.py](../../scripts/check_architecture.py) 机械校验。
- 原因：保持 `models -> core -> crud -> protocols -> services -> routes -> main` 的清晰单向分层，让列表查询、标题兜底派生与错误映射统一收口在业务服务层，避免路由层混杂 SQLite 细节。
- 排除：允许只读 GET 路由作为特例直接导入 `backend.crud`。
