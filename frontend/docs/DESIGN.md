# Frontend 设计

前端把 backend 的 session 快照作为对话事实来源，随后按 turn/message/tool ID 合并本次订阅的增量。浏览器通过 Next.js `/api/backend/*` 代理访问后端；不再调用已删除的 `/qa/tasks`，不再以全局 seq 或旧 replay 重建历史。页面地址继续使用 `/tasks/{session_id}`，地址中的 ID 就是后端会话 ID。

## 创建与恢复

首页先校验 PDF/DOCX 文件、20 文件和 32 MiB 单批上限，以及非空问题，然后执行：

```text
POST /chat/sessions -> session_id
POST /chat/sessions/{session_id}/files -> resources
POST /chat/completion {session_id, content} -> SSE
收到 session.snapshot -> 释放首问订阅 -> 跳转 /tasks/{session_id}
详情页 GET /resume?session_id=... -> 历史与当前轮快照 -> 后续增量
```

首页等待首问快照确认后再跳转，避免详情页在首问创建之前读到空闲快照。释放订阅不调用取消接口，后端持有的轮次继续执行。上传失败时不提交问题，手动重试复用已经创建的会话。已创建的会话立即进入本机侧栏，网络结果不确定时可以打开该会话检查状态。

后端没有会话列表接口。`session-store.ts` 仅在 localStorage 保存最近访问的会话 ID、状态提示和更新时间，使用独立的 recent-sessions key，不把旧 QA task ID 当作新会话迁移。历史消息、资源和当前运行态始终从 `/resume` 获取；缓存不可写时不阻断 API 操作。服务端渲染使用空缓存快照，避免 hydration 差异。

## 流与状态

`api.ts` 分开封装 JSON 接口和流接口。提问用带 JSON 请求体的 fetch POST，恢复用 fetch GET，因此不使用只能 GET 的 EventSource。非成功状态转换成 ApiError，流接口还校验 text/event-stream。

`session-stream.ts` 使用 TextDecoder 增量解码 UTF-8，并缓存跨网络分块的 SSE 行。它支持 LF/CRLF、多行 data 和心跳注释，只分发 session.snapshot/session.event。无效 JSON 报错；回调通知完成或 AbortSignal 取消时释放 reader，不继续等待后台回答。

`use-session.ts` 管理单个页面订阅，流程为：

```text
进入页面 -> GET resume -> snapshot 替换完整投影
session.event -> session-state 按 turn/message/tool ID 更新
终态或空闲快照 -> 关闭订阅
活跃流提前结束/网络错误 -> 退避后仅 GET resume
卸载/换会话 -> abort 旧订阅；连接代次拒绝旧请求的迟到结果
```

重连重新读取快照，不重放旧增量，不自动重发 POST，避免网络中断产生重复轮次。不可恢复的参数错误或 404 显示错误和手动恢复入口。运行中允许编辑下一轮草稿；待提交问题先显示本地占位，收到快照后由后端消息替换。

`session-state.ts` 的合并语义与 backend TurnView 对齐：

- snapshot 原样替换历史及当前轮。
- model_message.delta 按 message_id 追加；done 用完整 content 替换，不能重复拼接。
- retry 标记原尝试失败，新 message_id 独立展示。
- 工具按 tool_call_id 更新同一个条目，连续工具在 UI 折叠成过程组。
- turn.completed/failed/cancelled 结束轮次，将尚未完成的条目标为 interrupted；已结束轮次不接受迟到事件，旧轮终态不能清空新轮 ID。

用户主动取消时，POST /cancel 同时传 session_id、active_turn_id。取消成功的终态响应立即更新当前投影并释放订阅；关闭页面本身只断开订阅，不发取消。

## 文件与引用

`SessionDocuments` 展示快照中的 raw 资源，用资源 ID 生成下载和删除 URL。补传走 multipart `/chat/sessions/{id}/files`，删除走对应资源 DELETE；完成后用 resume 刷新全量资源和历史。文件变更与问答提交在页面上互斥，避免使用旧索引。

`/documents` 返回归档成员目录，`/documents/content?key=...` 返回全文。回答中的 `[label](documents/...)` 和带 documents 路径的 evidence 链接由 MarkdownEvidence 接管，通过 `/blocks?key=...` 读取对应原文。模型直接引用含空格的 Markdown key 时，先对链接目标中的空格编码，代码示例保持原文，避免 Markdown 把引用当成普通文本。数字引用按 Markdown 中的节点位置分配，StrictMode 重复渲染复用编号。路径通过查询参数编码，绝对地址和越界路径不会当作本会话证据。旧数字 selector 没有新协议映射时明确显示无法定位，不伪造引用结果。

原文用 Markdown 渲染，不再依赖后端已不返回的 display_html/source_selectors。历史和当前完成的无工具调用 assistant 消息使用数字引用。读取失败在文档面板显示；连续点击不同文档时，旧异步结果不能覆盖新选择。

## 组件边界与布局

- `upload-workbench.tsx`：首页文件选择、校验、创建和首问确认。
- `task-detail.tsx`：组合会话 hook、文件操作和证据选择。
- `session/workspace-shell.tsx`：顶部品牌与主题、最近会话抽屉、可调整宽度的来源分栏。
- `session/workspace-overview.tsx`：首页概览和问题建议；建议只填入草稿，仍由用户确认发送。
- `session/conversation.tsx`：历史和实时消息、工具组、重试和终态，滚动只在用户接近底部时跟随。
- `session/composer.tsx`：草稿、Enter/Shift+Enter 和稳定的发送/暂停按钮。
- `session/documents.tsx`：文档列表、原文件操作和引用原文。
- `session-types.ts`、`session-state.ts`、`session-stream.ts`、`use-session.ts`：分别负责契约、纯状态合并、传输解析、连接生命周期。

宽窗口采用左侧来源、右侧内容的双栏资料工作台，浅灰蓝底色、白色内容区和蓝色操作强调保持首页与会话页一致。顶部只显示 Agent Gate，不复制参考图的第三方品牌和实验标签。最近会话通过顶部菜单按需展开，避免挤占文档和对话空间。

首页左栏展示待上传文件及移除操作，主区给出上传、摘要和关键问题入口，底部放置首问输入。摘要与关键问题入口仅填写可编辑草稿，不自动调用模型。详情左栏将原文件列表、下载、补传、删除和原文阅读放在同一面板；来源搜索按文件名忽略大小写过滤原文件列表，不改变当前原文。详情输入框同样提供建议问题。没有后端接口的音频和分享操作不展示。

800px 以下使用 Documents/Chat 切换避免压缩聊天区域，点击引用自动进入原文。最近会话抽屉支持遮罩和 Escape 关闭。主题、键盘提交、输入法组合状态和拖动分栏仍沿用原工作台行为；轻量进入动画及操作悬停反馈遵循 prefers-reduced-motion。新增和修改的代码模块控制在 300 行以内；旧的未接入页面的 replay 组件不参与本次接口链路。

## 代理与验证

backend-proxy 原样转发 multipart/JSON，响应体按流透传，保留文件下载 Content-Disposition，避免二进制文件经文本解码损坏。请求 AbortSignal 传到上游 fetch，关闭浏览器订阅可释放后端订阅；后端轮次仍独立存在。Next.js 代理容量为 40mb，覆盖后端 32 MiB 文件内容及 multipart 开销，业务配额由后端最终校验。

测试按 API/SSE、纯投影、连接生命周期、首页、详情、引用和代理分层，每个测试文件在 tests/docs 下有对应说明。运行 `pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`。浏览器验证使用临时数据库和独立 storage 目录，避免修改用户已有会话。
