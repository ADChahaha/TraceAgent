# frontend/src/lib 关键决策

归属 [Frontend 设计](../../docs/DESIGN.md)，记录前端接口层、代理、主题与状态同步模块的长期取舍。

## 1. 以 `/resume` 快照为唯一事实来源，按服务端 ID 合并且重连永不重发 `POST`

- 决定：会话历史、资源和运行态始终以 backend `GET /resume` 快照为准，随后严格按服务端 `turn_id`/`message_id`/`tool_call_id` 合并 SSE 增量，禁止按正文内容指纹去重（确保同文本重复追问与多次重试各自独立保留）；活跃流提前断开或网络报错后，仅退避重试 `GET /resume`，绝不自动重发 `POST /completion`；会话目录直接请求 `GET /chat/sessions`，失败显错不回退 `localStorage`。
- 原因：防止网络抖动导致重复创建问答轮次或吞掉同文本追问，并保证多标签页与多浏览器共享真实后端状态。
- 排除：基于全局 `seq` 客户端回放重建历史；按正文指纹去重消息；断连自动重发 `POST`；把 `localStorage` 作为可见会话目录来源。

## 2. 使用 `fetch` + `TextDecoder` 解析 SSE，断连与取消语义分离

- 决定：提问走带 JSON 体的 `fetch POST`，恢复走 `fetch GET`，统一用 `session-stream.ts` 增量解码 UTF-8 SSE 流；关闭或切换页面只 abort 本地订阅，主动取消必须显式调用 `POST /cancel`。
- 原因：浏览器原生 `EventSource` 仅支持 GET 且不便于携带请求体与统一错误码处理；页面刷新或关闭不应误中断后台进行中的问答。
- 排除：使用原生 `EventSource` 封装流，或在页面 `beforeunload`/卸载时自动触发取消接口。

## 3. 首页与详情页共用逐文件串行上传队列

- 决定：通过 `use-file-uploads.ts` 对同一会话逐个串行调用 `POST /chat/sessions/{id}/files`，多次选文件按文件名去重追加合并，单文件失败保留重试入口且不阻塞后续文件；未发草稿在同页进程内映射交接、不进 URL。
- 原因：避免同会话并发触发后端文档归档与向量索引重建竞争，并保持多文件处理进度清晰可控。
- 排除：前端并发直传全部文件；新选文件覆盖前序待上传队列；把大段提问草稿塞进浏览器查询参数。

## 4. 采用 Next.js App Router BFF 代理（`/api/backend/*`）访问后端

- 决定：前端基于 Next.js App Router + TypeScript + Tailwind CSS + shadcn/ui 构建，测试采用 Jest + Testing Library；所有浏览器请求经 Next Route Handler（`/api/backend/*`）转发到 `BACKEND_BASE_URL`，原样透传 JSON、multipart、二进制下载、`AbortSignal` 与 SSE 流，代理请求体上限设为 `40mb`。
- 原因：消除浏览器 CORS 配置并隐藏后端真实地址，在同一代理层统一管控上传容量与流式连接释放。
- 排除：使用 Vite + Vitest 搭建纯前端并让浏览器直连后端服务。

## 5. 主题与响应式状态经 `useSyncExternalStore` 实现 SSR/Hydration 安全读取

- 决定：明暗主题通过单按钮切换并写入 `localStorage("agent-gate.theme")` 与 `html[data-theme]`，监听自定义事件与 `storage` 事件实现跨标签页同步；禁止在 Client Component 首帧 render 或 `useState` 初始化器中直接读取 `localStorage` 或 `window`，统一经 `useSyncExternalStore` 提供固定服务端快照（主题 `"light"`、窄屏 `false`）并由 `ThemeBootstrap` 挂载后同步。
- 原因：避免 Next.js 服务端预渲染 HTML 与客户端首次水合状态不一致触发 Hydration failed 报错。
- 排除：在初始 `useState` 中直接读 `localStorage` 或 `window.innerWidth`；使用多按钮或下拉菜单切换主题。
