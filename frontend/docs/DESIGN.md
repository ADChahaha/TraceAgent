# Frontend 设计

前端把 backend 的 session 快照作为对话事实来源，随后按 turn/message/tool ID 合并本次订阅的增量。浏览器通过 Next.js `/api/backend/*` 代理访问后端；不再调用已删除的 `/qa/tasks`，不再以全局 seq 或旧 replay 重建历史。页面地址继续使用 `/tasks/{session_id}`，地址中的 ID 就是后端会话 ID。

## 创建与恢复

首页选择文件时即校验 PDF/DOCX、20 文件和 32 MiB 上限，创建一次会话并将每个文件加入处理队列。后端文件接口返回时已经完成解析与索引，前端据此更新文件状态：

```text
选择文件 -> POST /chat/sessions（首次）-> 缓存会话 ID
每个文件 queued -> processing -> POST /chat/sessions/{id}/files（单文件）-> ready / failed
全部处理完成 -> 自动跳转 /tasks/{session_id} -> GET /resume 获取已处理资源
用户发送问题 -> POST /chat/completion -> SSE
```

`use-file-uploads.ts` 在首页和详情页共享逐文件队列。处理请求串行执行，避免同一会话重建索引时发生资源竞争；队列中等待的文件显示 Queued，正在处理的文件右侧显示旋转图标，成功显示就绪，失败行保留原因和单独重试入口。一个文件失败不会阻止后续文件处理。重复选择同名文件不重复排队；成功文件不随提问再次上传。处理中可编辑问题，发送按钮与 Enter 提交均被阻止；失败文件需重试或移除后提问。

首页删除已处理文件调用后端删除接口，移除排队或失败文件仅清理本地队列。删除失败保留原文件及错误提示。详情补传使用相同队列，资源变更后用 resume 刷新；删除刚补传的文件同时清理本地就绪占位。窄屏选文件后自动打开来源面板，使逐文件状态可见。

首页文件处理完成后自动进入固定会话地址，不要求先提问。未发送的问题通过同一页面进程内的草稿映射交接到会话输入框，草稿不放入 URL。复制 /tasks/{id} 到其他标签页通过 resume 读取相同文件和历史。上传队列尚未结束时不会导航，避免丢弃剩余待处理文件。

`workspace-list.tsx` 打开菜单时调用 GET /chat/sessions，从实际数据库读取最近 100 个会话；重新聚焦或本页会话更新时重读，迟到请求不能覆盖新结果。列表失败显示错误，不回退为隔离的浏览器缓存。localStorage 不再决定 workspace 是否可见，localhost、127.0.0.1 和不同浏览器只要代理到同一 backend，就共享目录。

`session-store.ts` 只负责本页列表刷新通知和导航时的草稿交接。历史消息、资源和当前运行态始终从 /resume 获取。空闲详情页每 5 秒及重新获得焦点时刷新服务端快照，以取得其他标签页新上传的文件或新对话；本页上传、删除、提问或接收回答期间停止空闲轮询，不因焦点切换打断正在执行的操作。服务端快照确认上传成功后清理本地占位，避免其他标签页删除文件后再次显示旧占位。

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

`SessionDocuments` 在左栏使用互斥的 Sources 和阅读视图。selection 为空时只显示来源列表，不预加载正文；选择文档或点击引用后，阅读器替换整个 Sources 区域，顶部保留文档切换和 Close document 关闭按钮。关闭清空 selection 并返回 Sources，重新点击引用仍可打开和定位。阅读视图没有来源列表挤占高度，全文滚动区域占满剩余空间，选中块使用淡黄色强调并保留所有前后章节。

来源列表展示快照中的 raw 资源，用资源 ID 生成下载和删除 URL。补传走 multipart `/chat/sessions/{id}/files`，删除走对应资源 DELETE；完成后用 resume 刷新全量资源和历史。文件变更与问答提交在页面上互斥，避免使用旧索引。

`/documents` 返回归档成员目录，前端按 documents 下的一级目录归为整份文档，文档选择器不再列出单个段落。`/documents/full?key=...` 一次读取所选文档的全部 Markdown 块，保留每块 key 和原有顺序。SourceReader 根据目录层级显示章节标题，再将所有块连续渲染到同一 article，段落、列表、表格保持 Markdown 展示。

回答中的 `[label](documents/...)` 和带 documents 路径的 evidence 链接由 MarkdownEvidence 接管。引用路径确定所属文档及目标块；同文档切换引用只更新 data-evidence-selected，并在原文滚动区定位，不替换全文、不重复请求。跨文档引用才加载另一整份文档。按 documents 资源 ID 和 location 判断版本，普通 5 秒会话同步不重新请求正文，也不反复滚动。异步迟到结果被忽略；缺失引用显示明确提示，不高亮其他段落。

数字引用使用 14px 黑底白字小圆标，字号 9px，默认即可见；悬浮仅轻微变灰并增加细轮廓，避免旧 replay 色彩变量缺失造成透明背景上的白字。模型直接引用含空格的 Markdown key 时，先对链接目标中的空格编码，代码示例保持原文，避免 Markdown 把引用当成普通文本。数字引用按 Markdown 中的节点位置分配，StrictMode 重复渲染复用编号。路径通过查询参数编码，绝对地址和越界路径不会当作本会话证据。旧数字 selector 没有新协议映射时明确显示无法定位，不伪造引用结果。

原文用 Markdown 渲染，不再依赖后端已不返回的 display_html/source_selectors。历史和当前完成的无工具调用 assistant 消息使用数字引用。读取失败在文档面板显示；连续点击不同文档时，旧异步结果不能覆盖新选择。

## 组件边界与布局

- `upload-workbench.tsx`：首页文件选择即处理、逐文件状态、创建会话和首问确认。
- `use-file-uploads.ts`、`session/upload-status.tsx`：单文件串行处理队列、重试/删除以及来源行右侧状态。
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

测试按 API/SSE、纯投影、连接生命周期、首页、详情、引用和代理分层，每个测试文件在 tests/docs 下有对应说明。运行 `pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`。普通运行从仓库根目录执行 scripts/start.sh，使用 .env 配置或默认 backend/backend.sqlite3 与 storage/data。独立测试库仅用于隔离验证，不能作为交付时的服务数据库；测试会话不会自动迁移到实际库。最近会话目录由 backend 共享，跨浏览器可从菜单选择，也可使用完整会话链接。旧 backend/backend/backend.sqlite3 属于此前从 backend 目录启动产生的旧 tasks 结构，不自动迁移到新 chat 会话。
