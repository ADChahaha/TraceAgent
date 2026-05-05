# Frontend Design

这份文档是 `frontend` 服务的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，负责上传文档、提交外部 `task_spec`、查看任务 replay，并在 replay 字段卡片里处理人工复核。

## 1. 目标与边界

`frontend` 不实现 OCR、字段抽取、route policy 或持久化逻辑，只把用户操作转换成 backend API 请求，并把 backend 返回的任务治理结果组织成可阅读的工作台界面。

核心链路是：

```text
用户选择一个或多个 PDF + task_type + task_spec JSON
  -> UploadWorkbench 校验 task_type、task_spec JSON 和 metadata JSON
  -> createTask 组装 multipart FormData
  -> Next route handler /api/backend/* 代理请求到 backend
  -> backend 创建任务后立即返回 task_id/pending/uploaded
  -> 前端把任务写入右侧最近任务列表并显示处理中
  -> UploadWorkbench 轮询 getTaskSummary(task_id)，终态后把最近任务更新为处理结果
  -> 用户点击最近任务进入 /tasks/{task_id}
  -> TaskDetail 读取 summary/result/replay/review
  -> ReplayReview 展示文档 HTML、outline、plan 和字段写入动作
  -> 字段卡片显示 route policy 的 accept/review/reject 结论
  -> 如果字段 route=review，在对应字段卡片里提交 revise_and_approve
  -> 刷新任务详情，并用最新 summary 回写最近任务列表
```

职责边界：

- `frontend` 只通过 `/api/backend/*` 访问 backend，不直接从浏览器跨域请求 FastAPI。
- `frontend` 必须显式提交 `task_spec`，不假设 backend 存在默认业务 schema。
- `frontend` 只在浏览器 `localStorage` 保存最近任务 id，不新增任务列表、登录、权限、多用户或批量任务能力。
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
      upload-workbench.tsx
      task-detail.tsx
      replay-review.tsx
      markdown-evidence.tsx
      ui/
    lib/
      api.ts
      backend-proxy.ts
      json.ts
      task-store.ts
      types.ts
      utils.ts
  tests/
    upload-workbench.test.tsx
    backend-proxy.test.ts
    task-detail.test.tsx
    docs/
```

模块边界：

- `src/app/` 只组织 Next.js 路由、布局和 API route handler。
- `src/components/` 放业务界面组件；业务组件通过 props 支持测试注入 API 函数。
- `src/components/markdown-evidence.tsx` 只渲染受控 markdown 子集，用于 evidence 文本，不执行 HTML。
- `src/components/ui/` 放 shadcn/ui 风格基础组件，不写业务流程。
- `src/lib/api.ts` 封装浏览器侧 backend 代理调用和错误语义。
- `src/lib/backend-proxy.ts` 封装 Next route handler 到 backend 的转发逻辑。
- `src/lib/types.ts` 维护与 backend API 对齐的 TypeScript 类型。

## 3. 关键流程

上传任务流程：

```text
用户在 / 看到多文件上传说明和 multipart 字段契约
  -> 选择一个或多个文件、填写 task_type、task_spec JSON、metadata JSON
  -> UploadWorkbench 只接受 PDF 文件，遇到其他后缀或 MIME 类型会在前端拦截
  -> task_type 输入框默认值和内置类型提示都为空，由用户自己决定任务类型
  -> task_spec JSON 默认只有空 task_name 和空 fields，不预置任何业务字段
  -> UploadWorkbench 检查 files 至少存在一个、task_type 非空
  -> parseJsonObject(task_spec, "task_spec") 校验必须是 JSON object
  -> parseJsonObject(metadata || "{}", "metadata") 校验可选 metadata
  -> FormData 以重复 files 字段写入每个文件，再写入 task_type、task_spec，metadata 非空时写入 metadata
  -> createTask POST /api/backend/tasks
  -> backend 返回 task_id、pending/uploaded、error_message=null
  -> addRecentTask 写 localStorage，把新创建任务插到右侧最近任务顶部并显示“处理中”
  -> 不跳转页面，避免用户误以为上传表单卡住
  -> getTaskSummary(task_id) 轮询 summary
  -> pending/processing 继续显示“处理中”和当前 stage
  -> waiting_review/completed/rejected/failed 显示“处理结果”、route 或失败状态
  -> updateRecentTask 只更新原位置的状态，不因为旧任务完成就把它移动到新任务上方
  -> failed 额外显示 error_message，点击 task_id 可进入详情页看完整原因
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
  -> ReplayReview 左侧展示 outline，中间用 iframe 展示 backend 的 display_html，右侧展示 plan 和当前动作对话
  -> reduceReplayFields 从 result.fields 建立字段名、显示名、agent_value 和 route
  -> 再把 review.fields 合并进去，补齐 agent 没有写入但 route_policy 要求 review 的字段
  -> 当前 action result 里如果返回 query_audit.summary、table_audit.summary 或其他 *_audit.summary，ReplayReview 会在该 action 的模型输出区显示诊断摘要
  -> 当前 action 是 set_field 时，在字段写入卡显示字段值、证据 chip、route badge 和 route_reason
  -> 字段值很长时，字段写入卡把字段内容放进独立滚动区，复核输入和提交按钮留在卡片底部；全屏且存在字段写入卡时，ReplayReview 根节点带 `has-field-write` 状态，让布局为底部复核区预留更高空间，避免 review 区被长列表顶出视口
  -> 如果没有 set_field action 但存在 needs_review 字段，replay 末尾显示同样的字段卡，并提示等待人工补录
  -> 字段卡上的 evidence chip 只把 iframe 文档滚动到对应 HTML 证据块，不改变当前 replay action 序号，避免用户查证据时被带回旧动作
  -> ReplayReview 的高亮边界只跟随当前 tool 实际返回给模型看的内容，不根据完整 HTML 自行扩展
  -> read_element(TABLE) 的结果是 table-ref 表结构摘要，因此只高亮原 HTML 里的 caption/表名和表头，不高亮整张表或表体内容
  -> 如果表格 HTML 没有 caption，ReplayReview 只高亮表头，不生成额外表摘要 marker
  -> read_element(TABLE)、整表 evidence chip 和左侧 overview 表格项都会把滚动锚点映射到 caption 优先、表头兜底，并靠上滚动
  -> table_extraction 的结果是 SQL rows，因此只高亮返回的 row_id，并在自动播放时逐行读取；columns 只作为结果数据展示，不触发表格列高亮
  -> set_field 的 evidence_ids 是字段写入依据，自动播放会按 iframe 里的真实 HTML 顺序从上到下读取，而不是按数组顺序乱跳
  -> 自动播放每个 action 时，先从当前 tool 可见证据推出 HTML 证据锚点
  -> 多个证据锚点按 iframe 当前 scrollY 与元素中心距离排序，优先滚到当前视口最近的 block
  -> 如果相邻 action 的 outline/block 锚点不变，跳过重复的左侧 outline 鼠标路径，只更新 iframe HTML 滚动、阅读线和高亮
  -> route=review 且 review handoff 标记 needs_review 时才显示复核输入
  -> route=accept 或 route=reject 只显示 badge 和原因，不提供编辑入口
  -> 用户在字段卡里提交 revise_and_approve
  -> submitTaskReview POST /tasks/{task_id}/review
  -> 成功后重新 loadTaskDetail
  -> updateRecentTask 用最新 summary 回写 localStorage，避免最近任务仍显示 waiting_review/review
```

## 4. 测试策略

前端测试使用 Next.js 官方常用的 `next/jest`、Jest 和 Testing Library，重点覆盖用户可观察行为和 backend 协议适配：

```text
组件测试
  -> 注入 createTask/loadTaskDetail/submitReview
  -> 验证表单校验、FormData 组装、复核 payload 和刷新行为

代理测试
  -> 注入 fetcher
  -> 验证 multipart 转发、backend URL 组装、错误状态和 detail 保留
```

每个测试文件都有 `tests/docs/` 下的一一对应说明文档，测试文档只解释测试目标和链路，不放开发设计内容。
