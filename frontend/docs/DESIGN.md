# Frontend Design

这份文档是 `frontend` 服务的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，当前负责展示 backend 数据库中的最近任务，并在任务详情里回放字段 trace、处理人工复核。

## 1. 目标与边界

`frontend` 不实现 OCR、字段抽取、route policy 或持久化逻辑，只把用户操作转换成 backend API 请求，并把 backend 返回的任务治理结果组织成可阅读的工作台界面。

核心链路是：

```text
浏览器打开 /
  -> HomeWorkspace 先从 localStorage 读取最近任务作为本地兜底
  -> UploadWorkbench 挂载后调用 GET /tasks 拉取 backend 数据库任务
  -> task-store 用 backend 返回的 TaskSummary 同步右侧最近任务栏
  -> 上传工作台顶部的单个主题按钮在 Light/Dark 间切换 Codex 风格主题，并写入 localStorage 与 html[data-theme]
  -> 首页显示上传表单和右侧最近任务栏，不承载内置实验入口
  -> 用户点击最近任务进入 /tasks/{task_id}
  -> TaskDetail 读取 summary/result/replay/review
  -> ReplayReview 展示文档 HTML、虚拟文件树、无框 agent 文字流和字段写入动作
  -> 字段写入区显示 route policy 的 accept/review/reject 结论
  -> 如果字段 route=review，在对应字段写入区提交 revise_and_approve
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
- `src/components/home-workspace.tsx` 负责加载 backend capabilities 并挂载上传工作台。
- `src/components/upload-workbench.tsx` 负责上传任务、轮询新建任务、从 backend 任务列表同步右侧最近任务栏。
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
  -> 用户点击上传工作台顶部的单个主题按钮时，applyStoredTheme 写入 localStorage、更新 html[data-theme] 并广播主题变更事件
  -> 调用 listTasks() / GET /tasks 获取 backend 数据库中的最近任务
  -> syncRecentTaskSummaries 将 backend TaskSummary 合并到 recent tasks 前部
  -> 右侧列表展示 task_id、处理中/处理结果 badge、stage/route 和失败原因
  -> 如果列表为空，显示空状态文案
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
  -> ReplayReview 使用类似文档协作工具 / Codex 的全屏三栏：顶部工具栏、左侧 Contents、中央 iframe 文档正文、右侧从上到下的 reason/tool 文字流
  -> 工作台配色跟随 Codex light/dark 主题：Light 使用白底、黑灰前景和浅灰面板，Dark 使用 `#181818` 背景、白色前景和深灰面板；`#339CFF` 只作为小范围 focus/控制 accent，当前文件、hover action、阅读线和 evidence 高亮使用中性灰，不再用大面积蓝色块
  -> 顶部工具栏只保留单行任务上下文：左侧返回后展示 `task_id / 当前选中文件名`，右侧只展示一个任务 status badge；当前文件名从正在播放或用户选中的 action path 匹配 replay.documents，支持多文件任务随当前文件切换
  -> 中间 iframe 是文档主画布，直接铺满中间容器；外层不加灰色 gutter、边框卡片或额外内边距
  -> iframe 内部使用通用白底文档排版：正文区域占满视口、稳定宽版心、15px 系统 UI 字体、克制标题/段落/列表间距和 booktabs 风格表格；这套样式不假设法律、论文或报告等具体文档类型
  -> ReplayReview 包装 display_html 时会兜底删除页码、页眉、页脚版本号等文档 chrome，避免旧任务的 `Page 2` 或 `428249v2` 在中间画布继续可见
  -> 回放动画的路径导航只发生在左侧文件树或文档结构树：当前 action 的 path / path+selector 证据先定位到左侧节点，再驱动 iframe 滚动和高亮
  -> 左侧虚拟文件树保留真实 path 作为定位 key，但 UI 展示成类似 LaTeX outline 的标题；`.md/.table/.list` 文件不直接显示扩展名，也会去掉文件名前导编号，例如 `001-Confidential.md` 展示为 `Confidential`
  -> 左侧文件树/文档结构采用较窄的 Contents 侧栏，不展示说明文案或展开/折叠双按钮；顶部只保留 `CONTENTS` 标签和一个关闭左栏的小按钮，关闭后中间文档区扩展并在左上角显示重新打开按钮，单个目录节点仍通过点击节点自身展开或收起
  -> 桌面布局下左侧文件树/文档结构和右侧 agent 文字流都通过竖向分隔条手动调整宽度；拖拽会暂停自动播放，左栏关闭后左侧分隔条消失但右侧分隔条仍可调整 agent 区宽度
  -> 左栏关闭时自动播放跳过左侧树形导航和鼠标路径动画，只保留 iframe 内的滚动、阅读线和高亮
  -> 文档结构过滤 `page_001` / `page_002` 这类分页容器节点，也过滤 `Page 2` 页码、页眉和 `428249v2` 这类页脚版本号；左侧只展示标题、段落、表格等实际可读结构
  -> 右侧不再渲染逐块工具时间线、backlog 面板或底部 dialogue；reason 和 tool 都是无边框、无底色的从上往下文字行，左键点击文字流继续下一步，hover 某条 action 时才显示“跳到这一步”和“只播放这一步”的小按钮
  -> reduceReplayFields 从 result.fields 建立字段名、显示名、agent_value 和 route
  -> 再把 review.fields 合并进去，补齐 agent 没有写入但 route_policy 要求 review 的字段
  -> 如果字段值是 enum tagged payload，ReplayReview 会把字段值显示成更适合人读的 variant，并把复核区切换成结构化编辑器
  -> enum 复核编辑器优先使用 backend 提供的 variants 下拉；如果没有 variants，则退回到手工输入 variant + payload 的兼容模式
  -> 提交 revise_and_approve 时，TaskDetail 会把 review_value 原样保留为结构化对象而不是字符串，后端收到的 payload 仍可保持 tagged 形状
  -> file_extraction_agent 的主展示对象是 replay.actions / trace.actions 中的真实 flat 工具调用，每条 action 形如 {tool_name,args,reason,result}
  -> ReplayReview 只从 action.reason 读取用户可见 reason；工具 wrapper 已把 args.reason 剥离，所以前端不再从 args.reason 或 metadata.reason 兜底，也不伪造“模型等待下一步动作”文案
  -> 右侧 reason 是普通正文段落；工具调用采用 Codex 风格的淡化运行文字行：read/read_element/read_section 用搜索图标，其余工具用终端图标，图标后直接是一句 `Ran/Read/Searched/Queried ...` 短摘要和少量 meta，不再拆出 tool_name 列、参数 chips、诊断卡或校验错误正文
  -> anchors action 不进入右侧文字流，也不会作为用户点击“下一步”时停留的可见步骤；它只保留给左侧虚拟文件树、selector 映射、iframe 高亮和自动阅读使用
  -> read 系列工具行使用模型实际读取对象的语义类型展示为 `Read paragraph/table/list 名称`，名称来自虚拟 path 的 basename 去掉编号前缀和 `.md/.table/.list` 扩展名，不再把 Markdown、表格或列表虚拟文件名当成右侧文案
  -> tree/read/anchors/query_table/search_elements/bind_evidence/review_field 返回的正文、候选片段、Rxxx/Sxxx/Ixxx 内容和 evidence_texts 不在右侧展示，只用于左侧虚拟文件树、iframe 高亮和自动阅读动画
  -> query_table/table_extraction 失败时右侧只显示“查询失败”工具行，0 行时只显示“未查到结果”工具行；两者都不把 table path、SQL 或 reason 当成文档读取锚点
  -> write_field action 展示无框字段写入区：field_id/display_name、status、value、final_evidence、route badge 和 route_reason；它替代旧 set_field 展示
  -> submit_result action 在右侧只保留工具行摘要；具体校验错误不作为右侧阅读内容展示
  -> 字段值很长时，字段写入区把字段内容放进独立滚动区，复核输入和提交按钮留在复核区底部；全屏且存在字段写入区时，ReplayReview 根节点带 `has-field-write` 状态，让布局为底部复核区预留更高空间，避免 review 区被长列表顶出视口
  -> 如果没有 write_field action 但存在 needs_review 字段，replay 末尾显示同样的字段写入区，并提示等待人工补录
  -> 字段写入区上的 evidence chip 只把 iframe 文档滚动到对应 HTML 证据块，不改变当前 replay action 序号，避免用户查证据时被带回旧动作
  -> ReplayReview 的高亮边界只跟随当前 tool 实际返回给模型看的 selector 或 Markdown 编号，不根据完整 HTML、path、SQL 或 reason 自行扩展
  -> bind_evidence 返回 path + selector + evidence_texts 时，ReplayReview 会先在 iframe HTML 对应文本上生成 inline evidence span；当前高亮只落在这段 inline 文本上，段落/列表项/表格块只用于左侧路径定位和滚动容器
  -> .md 证据只使用 anchors/read 形成的 Sxxx selector，高亮对应句子；.list 证据只使用 Ixxx item；.table 证据只使用 read/query_table 返回的 Rxxx row
  -> query_table 失败或返回 0 行时，不用 table path、SQL 或动作 reason 兜底高亮/读取文档，避免前端表现成模型看过查询结果之外的内容
  -> write_field 的 final_evidence 是字段写入依据，自动播放会按 iframe 里的真实 HTML 顺序从上到下读取，而不是按 selector 数组顺序乱跳
  -> 自动播放每个 action 时，先从当前 tool 可见 selector 推出 HTML 证据锚点
  -> 多个证据锚点按 iframe 当前 scrollY 与元素中心距离排序，优先滚到当前视口最近的 block
  -> 如果相邻 action 的虚拟路径或 HTML 证据锚点不变，跳过重复的左侧树形导航鼠标路径，只更新 iframe HTML 滚动、阅读线和高亮
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
  -> 验证首页只显示最近任务栏，不展示内置实验入口或上传表单
```

每个测试文件都有 `tests/docs/` 下的一一对应说明文档，测试文档只解释测试目标和链路，不放开发设计内容。
