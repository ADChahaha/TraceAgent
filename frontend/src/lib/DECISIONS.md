# frontend/src/lib 关键决策

归属 [Frontend 设计](../../docs/DESIGN.md)，记录前端接口层、流式订阅与状态同步模块的长期取舍。

## 1. 以 `/resume` 快照为唯一事实来源，重连永不重发 `POST`

- 决定：会话历史、资源和运行态始终以 backend `GET /resume` 快照为准，随后按 turn/message/tool ID 合并 SSE 增量；活跃流提前断开或网络报错后，仅退避重试 `GET /resume`，绝不自动重发 `POST /completion`；会话目录直接请求 `GET /chat/sessions`，失败显错不回退 `localStorage`。
- 原因：防止网络抖动导致重复创建问答轮次，并保证多标签页与多浏览器共享真实后端状态。
- 排除：基于全局 `seq` 客户端回放重建历史、断连自动重发 `POST` 或把 `localStorage` 作为可见会话目录来源。

## 2. 使用 `fetch` + `TextDecoder` 解析 SSE，断连与取消语义分离

- 决定：提问走带 JSON 体的 `fetch POST`，恢复走 `fetch GET`，统一用 `session-stream.ts` 增量解码 UTF-8 SSE 流；关闭或切换页面只 abort 本地订阅，主动取消必须显式调用 `POST /cancel`。
- 原因：浏览器原生 `EventSource` 仅支持 GET 且不便于携带请求体与统一错误码处理；页面刷新或关闭不应误中断后台进行中的问答。
- 排除：使用原生 `EventSource` 封装流，或在页面 `beforeunload`/卸载时自动触发取消接口。

## 3. 首页与详情页共用逐文件串行上传队列

- 决定：通过 `use-file-uploads.ts` 对同一会话逐个串行调用 `POST /chat/sessions/{id}/files`，单文件失败保留重试入口且不阻塞后续文件；未发草稿在同页进程内映射交接、不进 URL。
- 原因：避免同会话并发触发后端文档归档与向量索引重建竞争，并保持多文件处理进度清晰可控。
- 排除：前端并发直传全部文件，或把大段提问草稿塞进浏览器查询参数。
