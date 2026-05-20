# Frontend Design

这份文档是 `frontend` 的设计入口。`frontend` 是 Agent Gate 的浏览器工作台，当前只负责展示 backend 最近任务、任务详情和抽取回放，不再承载任何人工审核或 route gate。

## 1. 目标与边界

`frontend` 不实现 OCR、字段抽取或持久化逻辑，只把用户操作转换成 backend API 请求，并把 backend 返回的任务结果组织成可阅读的工作台界面。

核心链路是：

```text
浏览器打开 /
  -> HomeWorkspace 直接挂载 UploadWorkbench，不再先读取 capabilities 或显示旧上传首屏
  -> UploadWorkbench 先从 localStorage 读取最近任务作为本地兜底
  -> UploadWorkbench 挂载后调用 GET /tasks 拉取 backend 数据库任务
  -> task-store 用 backend 返回的 TaskSummary 同步左侧任务栏
  -> 顶部单个主题按钮在 Light/Dark 间切换 Codex 风格主题，并写入 localStorage 与 html[data-theme]
  -> 首页显示 Codex New Chat 形态的新任务界面：左侧任务栏 + 中央大标题 + 居中 composer
  -> 用户在 New Chat 界面关闭左侧任务栏时，只让中央 composer 变宽，不自动显示任何右侧 Progress 或 Inspector
  -> composer 用纸夹选择 PDF，把 textarea 中的 task_spec JSON 作为任务定义
  -> 前端校验 task_spec 是 object 且 task_spec.task_name 非空，用 task_spec.task_name 推导 backend task_type
  -> POST /tasks 返回 task_id 后写入左侧任务栏并轮询 GET /tasks/{task_id}
  -> HomeWorkspace 收到 created task 后立即跳转到 /tasks/{task_id}
  -> 用户点击左侧任务进入 /tasks/{task_id}
  -> TaskDetail 读取 summary/result/replay；处理中任务即使 has_trace=false 也会尝试读取 partial replay，让 document_processor 已产出的原文可以先显示
  -> TaskDetail 如果任务仍在 pending/processing 或 stream.state=running，每次进入或刷新详情页都会从 after_seq=0 打开 GET /tasks/{task_id}/events 的 EventSource，前端用事件 seq 去重并重建完整 live 流；没有 replay 时也渲染常规 Agent 工作区并显示 `Thinking`
  -> backend SSE 的命名事件会被 TaskDetail 直接消费，`agent.event` 先追加到 liveActions 实时渲染；ReplayReview 只把非空 model_message 和 tool_completed/tool_failed 转成可见 live action，tool_started/source_indexed 不进入 Agent 流；partial replay.actions 与 liveActions 会按 seq 和工具参数指纹合并，避免刷新从头重放时同一工具在 replay、started、completed 之间重复显示，同时保证已有 partial replay 时后续 read/write_field 仍会实时进入 Agent 流和字段 Progress；收到 `source_indexed` 后刷新 partial replay，终态事件再刷新 detail 收口
  -> ReplayReview 展示原顶部工具栏、左侧任务栏、中间 Agent 流和可由右上角按钮打开的右侧 Review 工作栏
  -> 字段 Progress 只按字段名排序展示紧凑字段列表，只负责导航和状态，不再展示 route 结论或人工编辑入口
  -> 用户点击字段 Progress 里的字段行时只在 Progress 内选中并查看字段摘要；用户点击 evidence://、read 或 add_candidate_evidence 时，在右侧 Review 工作栏按文件打开完整原文 tab，通过 replay.source_selectors 确认可定位的 path_id，再用 replay.display_html 中同名虚拟 path_id DOM id 跳到对应原文节点并高亮
  -> 刷新任务详情，并用最新 summary 回写最近任务列表
```

职责边界：

- `frontend` 只通过 `/api/backend/*` 访问 backend，不直接从浏览器跨域请求 FastAPI。
- `frontend` 会从 backend `GET /tasks` 拉取数据库任务；浏览器 `localStorage` 只作为本地兜底和新建任务即时反馈缓存。
- `frontend` 的类型定义镜像 backend 返回的状态、result、trace、replay 和 audit 响应。
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
  -> 左侧任务栏展示 task_id、处理中/处理结果、stage 和失败原因
  -> 中央显示 `What task should we run in agent_gate?` 和创建任务 composer
  -> 用户关闭左侧任务栏时，首页仍然只保留中央 composer，不自动打开任何右侧 Progress 或 Inspector
  -> 用户通过 composer 的隐藏 file input 选择一个或多个 PDF
  -> 用户在 textarea 粘贴 task_spec JSON
  -> parseJsonObject 校验 task_spec 必须是 JSON object
  -> 如果 task_spec.task_name 不是非空字符串，拦截并显示 `task_spec.task_name 不能为空`
  -> FormData 重复追加 files，写入 task_spec，并把 task_spec.task_name trim 后写为 task_type
  -> 不再提交 metadata 字段，也不再显示 task_type 独立输入框
  -> createTask POST /tasks 成功后 addRecentTask 立即更新左侧任务栏
  -> HomeWorkspace 通过 onCreated 调用 Next router 跳到 /tasks/{task_id}
  -> refreshTaskSummary 轮询 GET /tasks/{task_id}，直到 completed/failed 后停止
  -> 左侧任务栏仍允许用户点击任意 task_id 进入 /tasks/{task_id}
```

任务详情流程：

```text
/tasks/{task_id}
  -> TaskDetail 调用 loadTaskDetail(task_id)
  -> 先 GET /tasks/{task_id} 读取 summary
  -> summary.has_result 不是 false 时读取 result
  -> summary.has_result 或 summary.has_trace 不是 false 时读取 replay；如果任务仍在 running/pending/processing，也读取 replay 以拿到 partial display_html 和 live source_selectors
  -> 如果 summary 仍未终态，TaskDetail 在进入或刷新详情页时固定用 after_seq=0 打开 GET /tasks/{task_id}/events，让 backend 从头重放当前任务事件；内部游标只记录已见最大 seq，ReplayReview 再按 seq 合并 replay.actions 和 liveActions 去重
  -> TaskDetail 同时监听 `task.stage_changed`、`agent.event`、`task.completed`、`task.failed` 等 backend SSE 命名事件；内部游标随事件 seq 前进，但不会因为每条 live event 重建 EventSource
  -> ReplayReview 把 replay.actions 和 liveActions 转成同一条 action 流，优先保留 replay.actions，再追加 replay 中没有同 seq、也没有同工具参数指纹的 live action；因此刷新重放不会把同一工具显示两三次，字段 Progress 仍会随着新的 live write_field / set_field 即时更新，不等终态 result
  -> replay 仍为空且任务未终态时，ReplayReview 仍渲染常规任务工作台；中央 Agent 流显示 `Thinking`，后续 `agent.event` 会作为 liveActions 追加显示；如果 replay 已有 display_html 但 actions 仍为空，也继续显示 `Thinking`
  -> 如果当前浏览器环境没有可用事件流或暂时还没有 liveActions，TaskDetail 保留 1.5 秒轮询作为兜底，直到 replay/result 可用
  -> 如果 summary.status=failed 且带有 error_message，在详情页顶部展示失败原因
  -> 页面不渲染 result/trace/audit Tabs，只渲染 ReplayReview
  -> TaskDetail 让 replay 作为整页全屏工作台渲染，跳出根布局的最大宽度和页面 padding
  -> TaskDetail 同步 GET /tasks 和 localStorage 最近任务，作为工作台左侧任务栏数据
  -> ReplayReview 使用 Codex 式任务工作台：原顶部工具栏、左侧任务栏、中央 Agent 文字流和右侧 Review 工作栏
  -> 顶部工具栏不承载 `Review` 文件 tab 或当前文件名，只保留左侧任务栏 toggle、任务标题、右侧 status badge 和一个最右侧图标按钮用于开关右侧 Review 工作栏
  -> 右侧 Review 工作栏内部有文件式动态 tab，默认 tab 是 `Review`；证据链接和可定位工具行会在这里追加原文 tab
  -> 默认状态是左侧任务栏 + 中央 Agent 工作区；左侧任务栏只由用户点击顶部左侧 toggle 手动开关
  -> 右侧 Review 工作栏只由用户点击顶部最右侧图标按钮显式开关，或者由 evidence://、read、add_candidate_evidence 这类可定位入口自动打开；关闭左侧任务栏不会自动显示右侧 Review 工作栏
  -> 字段 Progress 是靠中间的右侧竖栏，主体是按字段名排序的紧凑字段列表：每行展示字段名、field status、短值、字段 summary 和证据数量
  -> 字段 Progress 不承载展开区，也不打开独立 Inspector；点击字段行只更新 Progress 内的选中态
  -> Agent 输出中的 Markdown 证据链接 `[文本](evidence://...)` 会阻止默认跳转，在右侧 Review 工作栏打开或切换对应文件的完整原文 tab
  -> read 和 add_candidate_evidence 工具行如果能解析到证据定位，会以 evidence href 的链接式工具行呈现，点击时复用同一套右侧原文 tab 打开逻辑；工具参数里的裸虚拟 path_id，例如 `0001.0000.0001`，会先规范成 `evidence://0001.0000.0001`
  -> 原文 tab 按 task_id 和文件隔离保存，tab 标题只显示解码后的 basename 文件名，不显示目录、URL 编码或 `%20`；同一文件只存在一个 tab，点击同一文件里的不同证据只更新该文件 tab 的 evidence selector 并重新定位高亮，多文件才打开多个文件 tab
  -> 原文查看器主体只显示完整原文渲染，不在 iframe 上方重复显示文件标题；原文内容按右侧框体 100% 宽度铺满重排，去掉纸张式灰底、外层留白、圆角和阴影，长表格、媒体、长词和预格式文本都收进框内，不保留固定纸面宽度或横向滚动条
  -> 原文 tab 用 iframe 隔离渲染 replay.display_html 的完整文档；backend 已把可读 block 的 DOM id 改写成虚拟 path_id，前端只在 replay.source_selectors 明确包含该 path_id 时滚动并高亮，例如 `evidence://0001.0000.0009` 只定位到 `id="0001.0000.0009"`；如果 evidence 使用 `evidence://range/<start>/<end>`，则前端按 `start` 所属文件打开原文 tab，并把这段连续 block 一起高亮；旧 replay 没有 source_selectors 时只打开原文文件 tab，不做 DOM id 或文本匹配兜底；用户点击 Markdown 短 quote 链接时也必须先有 source_selectors 定位到 block，才会在该 block 内部高亮 quote 文本本身；界面不展示内部 evidence URI、selector、字段映射或实现细节
  -> 中央 Agent 区底部固定对话输入框，左下角是加文件按钮，右下角是发送按钮；当前阶段只提供 UI 骨架，不直接创建新任务或追加消息
  -> 中央 Agent 文字流使用中间 Agent 工作区自己的动态三列布局：左侧弹性留白 / 阅读列 / 右侧弹性留白，阅读列在 Agent 自己的内容框内居中
  -> 当整页没有侧栏或只有一个侧栏可见时，Agent 中间文字框和输入框使用 `弹性留白 / 阅读列 / 弹性留白`；中间区变窄时先连续压缩两侧留白，留白归零后才压缩阅读列本身
  -> 阅读列被压窄时，Agent 正文、Markdown evidence 链接、单行 tool 摘要和折叠 tool group 摘要都在列内换行，不使用 `nowrap`、`overflow:hidden` 或 ellipsis 裁掉内容
  -> Replay stage 在窄视口也保持左栏 / Agent / 右侧 Review 的列布局，不把右侧 Review 原文栏堆到 Agent 下方
  -> 顶部工具栏左侧展示任务栏 toggle 和任务标题，右侧展示任务 status badge 和 Review 图标按钮，当前文件名只出现在右侧 Review 工作栏的文件 tab
  -> Agent 工具调用先按 action 顺序过滤掉 anchors/submit_result；空的 model_message 不进入文字流，非空 model_message 只作为文字段展示，不作为 tool 行；真实 tool 不包含也不消费 reason，连续 tool 直接按 run 折叠
  -> Agent 文字流根据用户当前位置决定是否跟随 liveActions：用户已经在底部时追加输出会继续滚到最新底部，用户离开底部阅读旧内容时保持当前 scrollTop；只有用户点击 evidence/read/add_candidate_evidence 打开原文时，右侧 iframe 才滚到对应原文节点
  -> 每个 tool run 如果只有 1 个 tool 就保持直出；如果连续包含多个 tool，就整组默认折叠成 tool group，不会先直出第一条 tool；用户手动展开后，同一组里后续 live tool 继续追加时保持展开，不会因为组内数量变化重新折叠
  -> tool group 折叠态显示一条类似 Codex 的自然语言摘要，概括这一段做了什么、涉及多少个文件/证据/字段；展开后恢复每个 tool 的单行明细
  -> tool 明细采用 Codex 风格的淡化运行文字行：tree/read/add_candidate_evidence/review_evidences/write_field 用语义图标，图标后是一句短英文摘要；tree 只显示 `Viewed outline`，read 只显示 `Read passage`，submit_result 不进入文字流
  -> write_field action 不在中间 Agent 流里展开字段大卡；字段状态、短值和字段 summary 进入字段 Progress 紧凑列表
  -> submit_result action 不进入中间 Agent 文字流
  -> evidence:// 链接和可定位工具行只打开或切换右侧文件原文 tab，定位到原文对应节点，不改变当前 replay action 序号，也不替换中央 Agent 工作区
```

## 4. 测试策略

前端测试使用 Next.js 常用的 `next/jest`、Jest 和 Testing Library，重点覆盖用户可观察行为和 backend 协议适配：

```text
组件测试
  -> 注入 loadTaskDetail
  -> 验证首页列表、右侧动态原文 tab、字段 Progress 和 replay 文字流行为

代理测试
  -> 注入 fetcher
  -> 验证 multipart 转发、backend URL 组装、错误状态和 detail 保留

首页测试
  -> mock 本地 recent tasks
  -> 验证首页显示 Codex New Chat 形态的新任务界面，不展示旧上传首屏
  -> 验证 task_spec.task_name 推导 task_type，PDF 通过重复 files 字段提交
```

每个测试文件都有 `tests/docs/` 下的一一对应说明文档，测试文档只解释测试目标和链路，不放开发设计内容。
