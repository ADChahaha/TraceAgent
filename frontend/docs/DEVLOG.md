# Frontend Devlog

last updated: 2026-05-23 04:15:14

## 2026-05-23 04:15:14

### 已完成工作

- 前端切换到 QA-only API：`/qa/tasks`、`/inputs`、`/events`、`/cancel`。
- 首页创建流程改为“上传 PDF + 首轮问题”，不再提交 `task_spec`、`task_type` 或字段 schema。
- 任务详情页改为 SSE 事件驱动的多轮 QA 工作台，直接渲染用户消息、模型过程消息、工具过程和 inline evidence link。
- 运行中右下角发送按钮切换为暂停按钮，点击后调用当前 task 的 cancel 接口。
- 同步更新 `frontend/docs/DESIGN.md` 和前端测试说明文档。

### 验证

- `npm test -- --runInBand`，结果 `6 suites / 29 tests passed`。
- `npm run lint` 通过。
- `npm run build` 通过。
- 浏览器打开 `http://127.0.0.1:3000` 检查首页上传与 QA 输入；backend 未启动时详情页能展示后端不可用错误。

## 2026-05-05 15:21:45

### 已完成工作

- 修复 replay 全屏模式下长字段值把人工复核区顶出视口的问题。
- `ReplayReview` 在存在字段写入卡时给根节点增加 `has-field-write` 布局状态，让全屏样式为底部字段卡和复核区预留更高空间。
- 字段写入卡内部改为字段内容区独立滚动，复核 textarea 和提交按钮固定留在卡片底部。
- 同步更新设计文档和任务详情测试说明，补充全屏长字段 review 的回归测试。

### 验证

- `pnpm --dir frontend test -- task-detail.test.tsx --runInBand`，结果 `20 passed`。

## 2026-05-04 02:20:00

### 已完成工作

- 新增 Review replay 动画界面，直接消费 backend 的 `actions + display_html + outline_tree + result`。
- Review 主体采用文档视图布局：左侧可展开 outline，中间 iframe 渲染 document_processor 的原始 display HTML，右侧显示 plan 进度，底部对话框显示模型每一步 reason。
- 支持 auto 播放、速度控制、对话框左键下一步、对话框上滚进入 backlog、右键退出 backlog、浏览器全屏视图。
- 每个 action 会定位相关 DOM id：outline 逐层展开并显示鼠标点击动画，文档区域滚动到 evidence，paragraph 做逐行阅读高亮，table/list 做块级高亮。
- `set_field` 时在文档证据处做写入强调，并在对话框展示字段值和 evidence chip；evidence chip 点击可暂停 replay 并跳转到对应证据。
- 人工 review 入口保留在 replay 下方：需要人工接管时，用户可以边看动画边填写需要修正的字段。
- 前端显示层隐藏内部 id：header 显示 `Header: 标题内容`，表格显示 `某 header 下面的表格`，表格行显示 `某 header 下面的表格第 N 行`；原始 id 仍用于定位和高亮。
- 修复直接进入 `/tasks/{task_id}` 或 failed task 时 replay 不加载的问题，只要 summary 有 trace/result 就拉取 replay。

### 当前进展

- 真实立命馆任务的 replay 页面已经能展示 `52` 步 actions，并可用于观察模型如何查找、读取、查询表格和写入字段。
- 当前可视化效果已经能体现可追踪性，但 plan 文本仍受模型 prompt 影响，偶尔会显得过度自信或过度规划。

### 验证

- `npm test -- --runInBand tests/task-detail.test.tsx tests/backend-proxy.test.ts`
- `npm run build`
- 手动打开 `http://localhost:3010/tasks/task_fc1c4d34a48742c9b7785f13f497ced8` 检查 replay 面板、outline、文档高亮、对话框、plan 和 evidence chip。

### 遇到的问题

- 初版 auto timer 和动画 timer 分离，导致对话框文字可能比鼠标/高亮快一条；已改为当前 action 动画结束后再推进 index。
- 用户手动滚动文档或点击 outline 后，自动动画不能强行把视图拉回；已在用户检查时暂停 replay。
- 原始 evidence id 可读性差，已改为显示标签层转换，不影响内部定位。

### 下一步

- 后续单独调 file_extraction_agent prompt：让模型 reason 更短、更贴近当前动作，让 plan 更适合前端逐项划掉展示。
