# Frontend Design

这份文档是 `frontend` 服务的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，当前负责展示 backend 数据库中的最近任务，并在任务详情里用 Codex 式任务工作台展示 Agent 流、字段 Progress 和 evidence Review。

## 1. 目标与边界

`frontend` 不实现 OCR、字段抽取、route policy 或持久化逻辑，只把用户操作转换成 backend API 请求，并把 backend 返回的任务治理结果组织成可阅读的工作台界面。

核心链路是：

```text
浏览器打开 /
  -> HomeWorkspace 直接挂载 UploadWorkbench，不再先读取 capabilities 或显示旧上传首屏
  -> UploadWorkbench 先从 localStorage 读取最近任务作为本地兜底
  -> UploadWorkbench 挂载后调用 GET /tasks 拉取 backend 数据库任务
  -> task-store 用 backend 返回的 TaskSummary 同步左侧任务栏
  -> 顶部单个主题按钮在 Light/Dark 间切换 Codex 风格主题，并写入 localStorage 与 html[data-theme]
  -> 首页显示 Codex New Chat 形态的新任务界面：左侧任务栏 + 中央大标题 + 居中 composer
  -> 用户在 New Chat 界面关闭左侧任务栏时，只让中央 composer 变宽，不自动显示任何右侧 Progress 或 Review
  -> composer 用纸夹选择 PDF，把 textarea 中的 task_spec JSON 作为任务定义
  -> 前端校验 task_spec 是 object 且 task_spec.task_name 非空，用 task_spec.task_name 推导 backend task_type
  -> POST /tasks 返回 task_id 后写入左侧任务栏并轮询 GET /tasks/{task_id}
  -> 用户点击左侧任务进入 /tasks/{task_id}
  -> TaskDetail 读取 summary/result/replay/review
  -> ReplayReview 展示左侧任务栏、中间 Agent 流、字段 Progress 竖栏和最右侧 Review 竖栏
  -> 字段 Progress 用紧凑字段列表展示 route policy 的 accept/review/reject 结论，只负责导航和状态，不在面板底部展开字段详情
  -> 用户点击字段 Progress 里的字段行时，最右侧 Review 竖栏打开该字段详情；如果字段 route=review，在这个 Review 详情里提交 revise_and_approve
  -> 用户点击 evidence:// 超链接时，最右侧 Review 为当前 task 新开或切换 evidence tab
  -> 刷新任务详情，并用最新 summary 回写最近任务列表
```

职责边界：

- `frontend` 只通过 `/api/backend/*` 访问 backend，不直接从浏览器跨域请求 FastAPI。
- `frontend` 会从 backend `GET /tasks` 拉取数据库任务；浏览器 `localStorage` 只作为本地兜底和新建任务即时反馈缓存。
- `frontend` 的类型定义镜像 backend 文档中的状态、route、review、result、trace 和 audit 响应。
- 任务详情页当前只把 replay 作为主展示面；底层 API 仍保留 trace 和 audit 读取函数，但 `loadTaskDetail` 不主动拉取它们。

## 2. 项目结构

当前实现结构如下：

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
      task-detail.tsx
      replay-review.tsx
      theme-bootstrap.tsx
      markdown-evidence.tsx
      ui/
    lib/
      api.ts
      backend-proxy.ts
      json.ts
      task-store.ts
      theme.ts
      types.ts
      utils.ts
  tests/
    home-workspace.test.tsx
    backend-proxy.test.ts
    task-detail.test.tsx
    docs/
```

模块边界：

- `src/app/` 只组织 Next.js 路由、布局和 API route handler。
- `src/components/` 放业务界面组件；业务组件通过 props 支持测试注入 API 函数。
- `src/components/home-workspace.tsx` 只负责挂载首页新任务工作台，不再读取 capabilities 或展示旧上传首屏。
- `src/components/upload-workbench.tsx` 负责首页 Codex New Chat 形态的新任务界面、task_spec/PDF 提交、轮询新建任务、从 backend 任务列表同步左侧任务栏。
- `src/components/theme-bootstrap.tsx` 在浏览器挂载后恢复 `agent-gate.theme`，把 `light/dark` 写到 `document.documentElement.dataset.theme`。
- `src/components/markdown-evidence.tsx` 只渲染受控 markdown 子集，用于 evidence 文本，不执行 HTML。
- `src/components/ui/` 放 shadcn/ui 风格基础组件，不写业务流程。
- `src/lib/api.ts` 封装浏览器侧 backend 代理调用和错误语义。
- `src/lib/backend-proxy.ts` 封装 Next route handler 到 backend 的转发逻辑。
- `src/lib/theme.ts` 封装 Codex light/dark 主题读取、写入、DOM 应用和主题变更事件。
- `src/lib/types.ts` 维护与 backend API 对齐的 TypeScript 类型。

## 3. 关键流程

首页与任务详情流程：

```text
用户在 / 打开工作台
  -> UploadWorkbench 先从 localStorage 读取 recent tasks
  -> ThemeBootstrap 从 localStorage 恢复 `agent-gate.theme` 并应用到 html[data-theme]
  -> 用户点击顶部的单个主题按钮时，applyStoredTheme 写入 localStorage、更新 html[data-theme] 并广播主题变更事件
  -> 调用 listTasks() / GET /tasks 获取 backend 数据库中的最近任务
  -> syncRecentTaskSummaries 将 backend TaskSummary 合并到 recent tasks 前部
  -> 左侧任务栏展示 task_id、处理中/处理结果、stage/route 和失败原因
  -> 中央显示 `What task should we run in agent_gate?` 和创建任务 composer
  -> 用户关闭左侧任务栏时，首页仍然只保留中央 composer，不自动打开任何右侧 Progress 或 Review
  -> 用户通过 composer 的隐藏 file input 选择一个或多个 PDF
  -> 用户在 textarea 粘贴 task_spec JSON
  -> parseJsonObject 校验 task_spec 必须是 JSON object
  -> 如果 task_spec.task_name 不是非空字符串，拦截并显示 `task_spec.task_name 不能为空`
  -> FormData 重复追加 files，写入 task_spec，并把 task_spec.task_name trim 后写为 task_type
  -> 不再提交 metadata 字段，也不再显示 task_type 独立输入框
  -> createTask POST /tasks 成功后 addRecentTask 立即更新左侧任务栏
  -> refreshTaskSummary 轮询 GET /tasks/{task_id}，直到 completed/waiting_review/rejected/failed 后停止
  -> 用户点击 task_id 进入 /tasks/{task_id}
```

代理转发流程：

```text
浏览器请求 /api/backend/{path}
  -> route.ts 读取 catch-all path
  -> forwardBackendRequest 用 BACKEND_BASE_URL 组装目标 URL
  -> GET/HEAD 不带 body，其余请求按 content-type 处理 body
  -> multipart/form-data 读取成 FormData，并删除旧 content-type 让 fetch 重新生成 boundary
  -> JSON 或普通请求读取 text body 并保留 content-type
  -> backend 响应的 status、statusText、content-type 和 body 返回给浏览器
```

任务详情流程：

```text
/tasks/{task_id}
  -> TaskDetail 调用 loadTaskDetail(task_id)
  -> 先 GET /tasks/{task_id} 读取 summary
  -> summary.has_result 不是 false 时读取 result，用于字段显示名、agent_value 和 route
  -> summary.has_result 或 summary.has_trace 不是 false 时读取 replay
  -> summary.status=waiting_review 时读取 review handoff
  -> 如果 summary.status=failed 且带有 error_message，在详情页顶部展示失败原因
  -> 页面不渲染 result/review/trace/audit Tabs，只渲染 ReplayReview
  -> TaskDetail 让 replay 作为整页全屏工作台渲染，跳出根布局的最大宽度和页面 padding
  -> TaskDetail 同步 GET /tasks 和 localStorage 最近任务，作为工作台左侧任务栏数据
  -> ReplayReview 使用 Codex 式任务工作台：顶部工具栏、左侧任务栏、中央 Agent 文字流、字段 Progress 竖栏和最右侧 Review 竖栏
  -> 默认状态是左侧任务栏 + 中央 Agent；左侧任务栏只由用户点击顶部左侧 toggle 手动开关
  -> 在任务详情页，左侧任务栏打开时自动关闭字段 Progress；左侧任务栏关闭时自动显示字段 Progress
  -> 字段 Progress 是靠中间的右侧竖栏，主体是紧凑字段列表：每行展示 route badge、字段名、field status、短值、证据数量和 route reason 摘要
  -> 字段 Progress 列表按 route 分成 Review、Reject、Accept 三组，用分割线和组标题隔开；顺序固定为 review 在最上面、reject 居中、accept 最下面
  -> 字段 Progress 不承载展开区；字段详情统一放进最右侧 Review 竖栏，避免 Progress 列表下方堆出第二块内容
  -> 字段 Progress 初始选中第一个需要 review 的字段；如果没有需要 review 的字段，就选中第一个字段，但不会自动打开 Review 竖栏
  -> 用户点击字段 Progress 行时，设置当前字段并打开最右侧 Review；Review 内展示完整字段值、证据 chip、route reason 和人工复核编辑器
  -> Agent 输出中的 Markdown 证据链接 `[文本](evidence://...)` 会阻止默认跳转，打开最右侧 Review 竖栏，并在该竖栏内为当前 evidence 新开或切换 tab
  -> 顶部右侧提供 Review toggle 按钮；按钮只控制最右侧 Review 竖栏，打开但没有字段详情或 evidence tab 时显示“选择一个字段或 evidence 链接查看详情”的空态
  -> Review 同时承载字段详情和 evidence tabs；打开或关闭 Review 不会改变左侧任务栏，也不会改变字段 Progress 的自动显示规则
  -> Review 的 evidence tabs 按 task_id 隔离保存；切换任务时只显示当前 task 的 evidence tabs，不共享上一任务打开过的 tab
  -> 中央 Agent 区底部固定对话输入框，左下角是加文件按钮，右下角是发送按钮；当前阶段只提供 UI 骨架，不直接创建新任务或追加消息
  -> 中央 Agent 文字流使用中间 Agent 工作区自己的动态三列布局：左侧弹性留白 / 阅读列 / 右侧弹性留白，阅读列在 Agent 自己的内容框内居中
  -> 当整页只有一个侧栏可见时，Agent 中间文字框和输入框启用 `小弹性留白 / 宽阅读列 / 小弹性留白`，参考 Codex 的宽文字流，空白只用于呼吸感而不过度挤窄正文；右侧同时出现 Field Progress 和 Review 时切到 `0 / 1fr / 0`，不再额外留空
  -> 中央 Agent composer textarea 与外框保持稳定内边距，底部按钮不压住输入文字
  -> 中央 Agent composer 与文字流复用同一平衡留白和居中阅读宽度，保证输入框和模型文字对齐
  -> 左侧任务栏顶部提供“新任务”入口，点击返回首页 Codex New Chat 形态的新任务界面；任务条展示 task_id、status/stage、route 和失败原因
  -> 不再展示任务级 Progress 面板；stream.state、stream.last_event_seq 和 tool call 计数不进入字段 Progress
  -> Review 面板展示当前字段详情，或当前 task 的 evidence tabs、当前 evidence URI、证据上下文和相关字段；它由字段行、evidence 链接和 Review toggle 驱动，不作为顶部固定三选一结果 tab
  -> 工作台配色跟随 Codex light/dark 主题：`globals.css` 统一提供 `--background/#ffffff`、`--foreground/#1a1c1f`、`--background/#181818`、`--card/#202020`、`--border/#303030` 和 `--codex-accent/#339cff` 等 token；ReplayReview 的面板、工具行、代码块和对话框都复用这些 surface 变量，不再写死白底
  -> 顶部工具栏只保留单行任务上下文：左侧 toggle 展示或隐藏任务栏，中间展示 `task_id / 当前文件名`，右侧只展示 Review 状态和一个任务 status badge
  -> Agent 流一次性渲染全部可见 action，不提供自动播放、下一步、速度条或单步播放
  -> Agent 流只从 action.reason 读取用户可见 reason；没有真实 reason 时只显示静态 tool 行，不伪造“模型等待下一步动作”文案
  -> Agent 工具调用采用 Codex 风格的淡化运行文字行：read/read_element/read_section 用搜索图标，其余工具用终端图标，图标后是一句 `Ran/Read/Searched/Queried ...` 短摘要和少量 meta
  -> anchors action 不进入 Agent 文字流；它只保留给 evidence selector 映射
  -> tree/read/anchors/query_table/search_elements/bind_evidence/review_field 返回的正文、候选片段、Rxxx/Sxxx/Ixxx 内容和 evidence_texts 不在 Agent 文字流里重复展示
  -> query_table/table_extraction 失败时只显示“查询失败”工具行，0 行时只显示“未查到结果”工具行；两者都不把 table path、SQL 或 reason 当成已阅读内容
  -> reduceReplayFields 从 result.fields 建立字段名、显示名、agent_value 和 route
  -> 再把 review.fields 合并进去，补齐 agent 没有写入但 route_policy 要求 review 的字段
  -> 如果字段值是 enum tagged payload，ReplayReview 会把字段值显示成更适合人读的 variant，并把复核区切换成结构化编辑器
  -> enum 复核编辑器优先使用 backend 提供的 variants 下拉；如果没有 variants，则退回到手工输入 variant + payload 的兼容模式
  -> 提交 revise_and_approve 时，TaskDetail 会把 review_value 原样保留为结构化对象而不是字符串，后端收到的 payload 仍可保持 tagged 形状
  -> write_field action 不在中间 Agent 流里展开字段大卡；字段状态进入字段 Progress 紧凑列表，字段细节进入最右侧 Review 竖栏
  -> submit_result action 在右侧只保留工具行摘要；具体校验错误不作为右侧阅读内容展示
  -> 字段值很长时，Review 字段详情把字段内容放进独立滚动区，复核输入和提交按钮留在详情底部
  -> 如果没有 write_field action 但存在 needs_review 字段，字段 Progress 仍从 review handoff 补出对应字段，并提示等待人工补录
  -> evidence chip 和 evidence:// 链接只打开或定位 Review，不改变当前 replay action 序号
  -> route=review 且 review handoff 标记 needs_review 时才显示复核输入
  -> route=accept 或 route=reject 只显示 badge 和原因，不提供编辑入口
  -> 用户在字段写入区提交 revise_and_approve
  -> submitTaskReview POST /tasks/{task_id}/review
  -> 成功后重新 loadTaskDetail
  -> updateRecentTask 用最新 summary 回写 localStorage，避免最近任务仍显示 waiting_review/review
```

## 4. 测试策略

前端测试使用 Next.js 官方常用的 `next/jest`、Jest 和 Testing Library，重点覆盖用户可观察行为和 backend 协议适配：

```text
组件测试
  -> 注入 loadTaskDetail/submitReview
  -> 验证首页列表、复核 payload 和刷新行为

代理测试
  -> 注入 fetcher
  -> 验证 multipart 转发、backend URL 组装、错误状态和 detail 保留

首页测试
  -> mock 本地 recent tasks
  -> 验证首页显示 Codex New Chat 形态的新任务界面，不展示旧上传首屏
  -> 验证 task_spec.task_name 推导 task_type，PDF 通过重复 files 字段提交
```

每个测试文件都有 `tests/docs/` 下的一一对应说明文档，测试文档只解释测试目标和链路，不放开发设计内容。
