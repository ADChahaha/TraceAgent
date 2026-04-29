# Frontend Design

这份文档是 `frontend` 服务的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，负责上传文档、提交外部 `task_spec`、查看任务结果、处理人工复核，并展示 trace 与 audit。

## 1. 目标与边界

`frontend` 不实现 OCR、字段抽取、route policy 或持久化逻辑，只把用户操作转换成 backend API 请求，并把 backend 返回的任务治理结果组织成可阅读的工作台界面。

核心链路是：

```text
用户选择一个或多个 PDF/DOCX + task_type + task_spec JSON
  -> UploadWorkbench 校验 task_type、task_spec JSON 和 metadata JSON
  -> createTask 组装 multipart FormData
  -> Next route handler /api/backend/* 代理请求到 backend
  -> backend 同步创建任务并返回 task_id/status/stage
  -> 前端保存最近任务到 localStorage 并跳转 /tasks/{task_id}
  -> TaskDetail 读取 summary/result/trace/review/audit
  -> trace.steps 展示 document_processor、file_extraction_agent、route_policy_agent 的执行过程
  -> trace.agent_trace 展示 backend 持久化的每次 agent 调用 request/response/trace 摘要
  -> 如果任务 waiting_review，展示 evidence/actions 并提交 review payload
  -> 刷新任务详情，展示最终字段、证据和审计记录
```

职责边界：

- `frontend` 只通过 `/api/backend/*` 访问 backend，不直接从浏览器跨域请求 FastAPI。
- `frontend` 必须显式提交 `task_spec`，不假设 backend 存在默认业务 schema。
- `frontend` 只在浏览器 `localStorage` 保存最近任务 id，不新增任务列表、登录、权限、多用户或批量任务能力。
- `frontend` 的类型定义镜像 backend 文档中的状态、route、review、result、trace 和 audit 响应。

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
  -> task_spec JSON 默认填入 agent/scripts/run_civilized_dormitory_extraction.py 中的文明寝室四字段模板
  -> UploadWorkbench 检查 files 至少存在一个、task_type 非空
  -> parseJsonObject(task_spec, "task_spec") 校验必须是 JSON object
  -> parseJsonObject(metadata || "{}", "metadata") 校验可选 metadata
  -> FormData 以重复 files 字段写入每个文件，再写入 task_type、task_spec，metadata 非空时写入 metadata
  -> createTask POST /api/backend/tasks
  -> backend 返回 task_id/status/stage
  -> addRecentTask 写 localStorage，失败时不阻断任务创建
  -> onCreated 跳转 /tasks/{task_id}
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
  -> 根据 summary.has_result/has_trace/status 决定是否读取 result、trace、review
  -> 非 failed 状态尝试读取 audit，404/409 返回 null
  -> 页面用 Tabs 展示 result、review、trace、audit
  -> trace tab 先由 AgentExecutionSteps 渲染 trace.steps，按调用顺序展示 agent 名称、阶段、状态、时间、文件摘要、file_extraction_agent 字段决策过程和 route 统计
  -> 字段决策过程优先展示 backend 返回的 agent_process.process_steps，按 broad_extraction、field_resolution/tool、final_result 三段说明候选证据、工具动作和最终结果
  -> AgentRawTrace 渲染 trace.agent_trace，按 sequence 展示每次 agent 调用的 agent/stage/status 和 request/response/trace key 摘要，JSON 明细放入可展开区域
  -> review tab 对 waiting_review 字段展示 agent_process，包含字段值、证据状态、三段过程、reason、field_reference/global_lookup/validation_rule 等 action 明细
  -> audit tab 对 field_commits 展示最终提交记录，并在每条提交下方展示对应 agent_process 和三段过程
  -> review/trace 中的 evidence_texts/texts 先交给 MarkdownEvidence 渲染标题、列表、标准/紧凑表格、加粗和行内代码
  -> waiting_review 时把 agent_value 作为默认复核值
  -> 用户提交 revise_and_approve
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
