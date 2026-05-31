# Frontend Design

这份文档是 `frontend` 的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，当前只适配 QA-only backend：用户上传多文档并提问，前端显示模型边阅读边回答的过程流、inline evidence link、多轮追问和取消入口；最终回答会把 evidence 渲染成紧跟句子的数字 citation。

## 1. 基本工作方式

核心链路是：

```text
浏览器打开 /
  -> HomeWorkspace 挂载 UploadWorkbench
  -> UploadWorkbench 从 localStorage 读取 recent tasks 作为首屏兜底
  -> 挂载后调用 GET /qa/tasks 同步 backend 最近任务
  -> 用户选择一个或多个 PDF/DOCX，并在 composer 输入首轮问题；重复点 Add document 时会把新选择追加到当前文件列表
  -> composer 键盘语义统一为 Enter 提交、Shift+Enter 换行
  -> 首页左侧 Tasks sidebar 默认 224px，打开时始终保留 sidebar / resize handle / main 三列，用户可拖拽或用键盘调整宽度
  -> 前端校验 files 非空、文件是 PDF 或 DOCX、问题非空
  -> POST /qa/tasks，只用 multipart files 创建 QA task
  -> HomeWorkspace 跳转 /tasks/{task_id}
  -> 后台提交 POST /qa/tasks/{task_id}/inputs，把首轮问题写入同一个 task
  -> TaskDetail GET /qa/tasks/{task_id} 读取 task summary
  -> 同一个 task detail 响应携带 documents[].display_html 和 source_selectors，供 evidence 点击打开右侧 review 文档
  -> 如果后续补详情返回的 stream seq 旧于当前 SSE，前端只保留当前运行态/seq，并继续合并补回来的 documents/display_html/source_selectors
  -> TaskDetail 打开 GET /qa/tasks/{task_id}/events?after_seq=0
  -> 提交追问时先插入 optimistic message，并在其后追加 assistant 侧 Codex 式上下跳动 Thinking；同时立刻用当前 last seq 重新连接 SSE，不等待 POST /inputs 返回
  -> EventSource 遇到 error 时不由前端主动 close，交给浏览器原生重连，只有组件卸载或主动换 after_seq 时才关闭旧连接
  -> SSE agent.event(model_message) 渲染模型过程回答，保留 [label](evidence://...) inline link
  -> 若 model_message 带 is_final=true，则前端把正文里的 evidence link 渲染成紧跟原句的数字 citation，不单独生成 Sources 行
  -> 连续 tool_completed/tool_failed 默认折叠成 Codex 式轻量过程行，只显示聚合计数摘要，展开后显示每个 tool
  -> turn.completed / turn.cancelled / turn.failed 结束本轮，composer handler 恢复允许提交下一轮
  -> 如果 cancel 后 backend 先把 summary 切回 ready/idle，再由后续 SSE 终态事件或 refresh 回填，前端会以最新 summary 为准解除本地 running/cancelling 锁定，避免按钮一直停在 Pause 态
  -> 用户继续追问时 POST /qa/tasks/{task_id}/inputs，并按当前 seq 重新连接 SSE 续读新事件
  -> 用户在运行中点击 composer 的固定主操作按钮时 POST /qa/tasks/{task_id}/cancel
```

职责边界：

- `frontend` 只通过 `/api/backend/*` 访问 backend，不直接跨域请求 FastAPI。
- `frontend` 不保存模型对话事实，只把 backend 的 `TaskSummary` 和持久化 `TaskEvent` 渲染成工作台。
- `frontend` 不单独请求旧 replay；QA evidence review 使用现有 task detail 响应里的 `documents[].display_html` 和 `source_selectors`。
- `localStorage` 只保存 recent task 摘要，不能作为 QA messages 的事实来源。
- `frontend` 不再读取旧 result/replay/trace/audit，也不再发送 `task_spec`、`task_type` 或字段 schema。
- `frontend` 的运行时 UI 文案、aria label、错误兜底和页面 metadata 统一使用英文，避免首页、详情页和旧 replay 组件出现中英文混用。

## 2. 项目结构

```text
frontend/
  src/
    app/
      api/backend/[...path]/route.ts
      page.tsx
      tasks/[taskId]/page.tsx
      layout.tsx
      globals.css
    components/
      home-workspace.tsx
      upload-workbench.tsx
      task-detail.tsx
      markdown-evidence.tsx
      theme-bootstrap.tsx
      ui/
    lib/
      api.ts
      backend-proxy.ts
      task-store.ts
      theme.ts
      types.ts
  tests/
    backend-proxy.test.ts
    frontend-copy.test.ts
    home-workspace.test.tsx
    task-detail.test.tsx
    upload-workbench.test.tsx
    docs/
```

模块边界：

- `src/app/` 只组织 Next.js 路由、布局和 backend proxy route。
- `src/components/upload-workbench.tsx` 负责首页 QA task 创建、首问提交、recent task 任务栏和主题按钮。
- `src/components/task-detail.tsx` 负责 QA task 详情、SSE 事件流、追问 composer 和取消按钮。
- `src/components/markdown-evidence.tsx` 用 `react-markdown + remark-gfm` 渲染模型回答，支持 GFM 表格、连续编号列表和嵌套列表；默认保留 `evidence://` inline link 的点击接管，最终回答模式会把 evidence link 原地渲染成 `1`、`2` 这类数字 citation marker，并剥掉模型可能附加的尾部 Sources 区。
- `src/lib/api.ts` 封装 `/api/backend/qa/*` 调用、SSE URL、EventSource 创建和错误语义。
- `src/lib/task-store.ts` 只缓存 task 摘要，包括 status、stage、document_count、active_turn_id 和 stream。
- `src/lib/backend-proxy.ts` 透明转发 multipart、JSON 和 text/event-stream。

## 3. 关键流程

首页创建 QA task：

```text
用户在首页选择 PDF/DOCX files 和输入 question
  -> isSupportedDocumentFile 校验每个文件
  -> question.trim() 校验非空
  -> FormData append("files", file) 多次
  -> createTask(formData) POST /api/backend/qa/tasks
  -> addRecentTask(created)
  -> onCreated(created) 立刻跳转详情页
  -> 后台 createTaskInput(created.task_id, question) POST /api/backend/qa/tasks/{task_id}/inputs
  -> 任务状态和回答事件交给详情页 EventSource 同步，首页不轮询 task summary
```

任务详情多轮 QA：

```text
TaskDetail(task_id)
  -> loadTaskDetail(task_id) 只读取 GET /api/backend/qa/tasks/{task_id}
  -> 保存 summary.documents/source_selectors 作为右侧 review 文档索引
  -> createTaskEventSource(task_id, 0)
  -> appendTaskEvent 按 seq 去重合并事件
  -> SSE agent.event(source_indexed) 立即把 payload.result.source_selectors 合并进当前 summary；如果当前详情缺少 documents/display_html，则补一次 GET /qa/tasks/{task_id}
  -> 补详情如果比当前 SSE seq 旧，不覆盖当前 status/stage/stream/active_turn_id，但仍合并它带回的 documents/display_html 和 source_selectors
  -> optimisticEvents 保存本地刚提交但还没被 SSE 确认的 user message
  -> eventToStreamItem 把 message.created / agent.event 转成可见流
  -> agent.event(type=model_message) 会读取 payload.is_final；普通过程消息保持 inline evidence，最终回答把 evidence link 原地渲染成句尾数字 citation，不再另起 Sources 行
  -> 点击 Markdown evidence link 时，从 evidence:// path 去掉 S/I/R inline selector，查 source_selectors 得到 display_html DOM id
  -> 如果 evidence 是 `evidence://range/{start}/{end}`，则按 source_selectors 收集同一层级 start 到 end 范围内的所有 DOM id
  -> 如果 evidence 指向文件夹/section 级虚拟路径且没有直接 source_selector，则把虚拟路径本身作为 header DOM id/data-element-id 定位，不跳到下面的第一个子节点
  -> 为兼容旧任务，若虚拟路径 header id 也不存在，则只用 evidence 链接文本匹配同名 h1-h6 heading，不匹配正文 block
  -> 只要 summary.documents 里存在 display_html，就默认显示 review 文档；review slot 位于 Agent 左侧，Agent 始终在最右侧主工作区
  -> review 不再渲染额外标题栏、文件名 meta 或关闭按钮，iframe 直接占满 review slot，让 display_html 自己的正文标题成为首屏内容
  -> review iframe 会把 display_html 压成干净的阅读页：白底、居中窄阅读列、正文左对齐、较小字号、紧凑段距，标题/表格/代码块基础排版统一，避免原始 HTML 的 page 壳和工具栏感
  -> 点击 inline evidence 后复用当前 review iframe；Sxxx 优先定位 `{block_id}_sentence_000` / `{block_id}_sent_000` / `{block_id}_s_000` 这类句子节点，找不到时回退父 block；Ixxx 优先定位 `{block_id}_item_000` 这类列表项，Rxxx 优先定位 `{table_id}_tr_001` 这类表格数据行，range 会同时高亮多个范围节点并滚到第一个节点
  -> review panel 默认 560px，范围 480-960px，通过 Agent 左侧的 resize separator 拖拽；键盘 ArrowRight 增宽、ArrowLeft 缩窄
  -> 如果 display_html 自带 page-like 纸张框（page 背景、阴影、内边距），前端会把这层外框压平，只保留正文排版和 evidence 高亮
  -> 同一文档内切换 evidence 时不重写 srcDoc，而是在 iframe.contentDocument 内移除旧 current evidence、给新 id/data-element-id 加 marker
  -> 如果 task detail refresh 带回新的 display_html，写入 iframe srcdoc 前先记录当前滚动位置；若刷新后没有定位到 evidence 目标，就恢复旧滚动位置，避免 review 跳回顶部
  -> 对新 marker 调 scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" })，并用较大的 scroll-margin 让高亮落在靠上但适合阅读的位置
  -> review 与左侧任务栏同时打开时，stage 会给 Agent 列保留紧凑最小宽度，并把 review 可用宽度限制在剩余空间内；Agent slot 小于 360px 时自动收紧内边距、气泡和字号，保证最右侧对话仍可读
  -> Agent 对话流和输入框共用同一个水平 inset；content frame 和 composer frame 都使用 `0 / minmax(0, 1fr) / 0`，让正文、工具行和 composer 在当前 Agent slot 内同宽铺开，左右面板只改变外层 stage 的可用宽度，不再用 viewport 或侧栏宽度额外偏移内容列
  -> Agent 对话流只在用户已经接近底部时跟随 SSE 新消息；用户向上滚动阅读历史后，新消息不能强制把滚动位置拉回最底部
  -> applyEventToSummary 用事件更新 running/ready 状态
  -> turn terminal event 后清理运行态并刷新 summary
  -> 用户提交追问 createTaskInput(task_id, content)
  -> 任务详情 composer 同样使用 Enter 提交、Shift+Enter 换行
  -> 立即清空 composer，把 content 作为右侧用户消息显示，并在 assistant 左侧显示上下跳动的 Thinking
  -> composer textarea placeholder 固定为 `Ask a follow-up question`；右下角只有一个固定主操作按钮，running/ready 状态变化不能改写输入框或主按钮 DOM/class/尺寸，只在按钮内部切换 Send/Pause icon 可见性，避免 SSE 事件让输入区闪烁
  -> eventSubscriptionKey +1，用当前 last seq 重新打开 EventSource 续读；这个动作发生在 POST /inputs 之前，避免新 turn 事件已经写入但前端仍停在旧连接
  -> 左侧 Tasks sidebar 复用首页同一套 224px 默认宽度和 resize handle，打开时保持三列布局
  -> 用户在运行中点击固定主操作按钮 cancelTask(task_id)
```

事件渲染规则：

- `message.created` 且 `role=user|assistant`：渲染为无显式角色标签的对话消息；用户消息靠右，assistant 消息靠左。
- `agent.event` 且 `payload.type=model_message`：渲染为左侧 assistant 消息；`is_final=false` 的过程回答支持 inline evidence link，`is_final=true` 的最终回答把 evidence link 原地渲染为数字 citation marker，marker 点击仍打开右侧 review。
- `agent.event` 且 `payload.type=tool_completed|tool_failed`：渲染为工具过程行；连续工具事件会默认折叠成一行低权重摘要，例如 `Read 1 passage, inspected 1 evidence, 1 search`，默认摘要只统计动作数量，不写失败状态；展开后也只显示动作和内容类型，例如 `Listed current level`、`Read paragraph`、`Inspected table row`，不展示具体 evidence/path/locator；`ls` 使用当前层列表语义，不再显示成 outline/tree；`tool_failed` 使用普通工具行颜色，不做红色失败态；read/inspect 行如果带 locator 可点击打开右侧 review；展开明细和摘要行左边缘对齐，展开后同一组继续追加新 tool 时保持展开。
- `turn.cancel_requested/cancelled/failed`：渲染简短状态行。
- 空 `model_message` 和内部生命周期事件不进入可见对话流。

取消语义：

```text
summary.active_turn_id 或 stream.state=running
  -> composer textarea 保持可输入，用户可以先写下一轮草稿
  -> composer 右下角保持一个固定主操作按钮，不用 running 状态切换 disabled/aria-disabled/class 或追加第二个按钮
  -> 同一个按钮内同时挂载 Send 和 Pause icon；空闲时显示 Send，running 时显示 Pause，只切 data-visible，不改变按钮节点和尺寸
  -> 空闲时同一个按钮走 submit handler；空内容时 no-op，问题非空时提交追问
  -> running 时同一个按钮走 cancel handler，调用 POST /qa/tasks/{task_id}/cancel
  -> backend 写入 cancel 事件并关闭/结束当前 turn
  -> SSE 收到 terminal turn event 后清理运行态；如果 cancel 期间任务快照已经恢复为 ready/idle，前端也会同步释放本地 running/cancelling 锁定，稳定主按钮重新允许提交
```

## 4. 测试策略

```text
API 测试
  -> 验证 /api/backend/qa/tasks、/inputs、/cancel、/events URL 与请求体

首页组件测试
  -> 验证 PDF/DOCX + 首问创建 QA task
  -> 验证不再发送 task_spec / task_type
  -> 验证 recent task 同步和主题按钮

任务详情组件测试
  -> 注入 fake EventSource
  -> 验证用户消息、模型消息、tool 过程、过程 inline evidence 和最终回答句尾数字 citation 渲染
  -> 验证追问复用 task_id
  -> 验证 running 时固定主操作按钮调用 cancel，composer 不追加第二个按钮，并只在同一按钮内切换 Send/Pause icon 可见性

代理测试
  -> 验证 multipart 原样转发
  -> 验证 text/event-stream 不被完整缓冲

Copy 契约测试
  -> 扫描 frontend/src 下运行时源码
  -> 去掉注释后检查字符串和 JSX 文本不含中文字符
```

每个测试文件都有 `tests/docs/` 下的一一对应说明文档，测试文档只解释测试目标和链路，不放开发设计内容。
