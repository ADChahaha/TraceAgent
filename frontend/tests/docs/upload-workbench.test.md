# `upload-workbench.test.tsx`

这组测试覆盖首页 QA 新任务入口。测试用注入的 `createTask`、`createTaskInput` 和 `listTasks` 隔离真实 backend，只验证首页任务栏、任务栏 resize、PDF/DOCX 上传、首轮问题提交、英文 UI 文案和主题切换这些用户可见行为。

## 测试链路

```text
用户打开 /
  -> UploadWorkbench 渲染 Codex New Chat 形态工作台
  -> 服务端首帧不读取 localStorage，客户端挂载后同步本地 recent tasks
  -> 浏览器挂载后调用 GET /qa/tasks 同步 backend 最近 QA task
  -> 左侧任务栏默认宽度是 224px，可通过 resize separator 拖拽或键盘调整
  -> 用户选择一个或多个 PDF/DOCX
  -> 反复点击 Add document 时，新的选择会追加到当前文件列表，而不是覆盖上一次选择
  -> 用户在 composer 输入首轮 QA 问题
  -> Enter 直接提交，Shift+Enter 在问题里保留换行
  -> 前端校验至少一个 PDF 或 DOCX、文件类型是 PDF/DOCX、问题非空
  -> FormData 只重复追加 files，不再发送 task_spec / task_type
  -> POST /qa/tasks 创建多文档 QA task
  -> 左侧任务栏立即显示新 task，状态以英文 status / stage 呈现，并跳转详情页
  -> 后台 POST /qa/tasks/{task_id}/inputs 提交首轮问题
  -> 首页不轮询 task summary，后续状态和回答事件由详情页 EventSource 同步
```

## 测试函数

- `首页默认就是 Codex 式新任务界面，不再显示旧上传首屏`：验证首页只显示任务栏和 QA composer，不显示旧上传工作台、task_type、metadata 或执行态 Agent 流。
- `首页服务端首帧不读取 localStorage，避免服务端 HTML 与客户端 hydrate 不一致`：验证 SSR 不读取浏览器缓存，客户端挂载后再显示本地 recent task。
- `New Chat 关闭左侧任务栏后不自动显示右侧 Progress`：验证首页关闭左栏后仍只保留中央 QA composer。
- `首页左侧任务栏默认宽度和详情页一致，并支持键盘调整`：验证首页任务栏默认 224px，范围是 176-360px，并能通过键盘和拖拽调整。
- `启动时从 backend 任务列表加载左侧任务栏`：验证首页会从 `GET /qa/tasks` 同步数据库任务到左侧栏。
- `QA composer 会创建 PDF/DOCX 多文档 task 并提交首轮问题`：验证上传 PDF + DOCX 后，前端只提交 `files`，拿到 task 后用同一 task 调 `/inputs` 发送首问。
- `再次选择文档会追加到已选文件而不是覆盖`：验证多次打开文件选择器时，后一次选择会累加进当前文件列表，并在提交时一次性发送全部 `files`。
- `QA composer 用 Enter 提交问题，Shift Enter 保留换行`：验证首页 composer 的键盘语义，Shift+Enter 只插入换行，Enter 才创建 task 并提交包含换行的首问。
- `没有文档或问题为空时不会创建任务`：验证缺少 PDF/DOCX 或空问题会用英文错误提示在前端拦截，不调用 backend。
- `已选择的文档可以逐个移除`：验证每个文件 chip 都能通过英文 remove 按钮独立移除。
- `创建任务后左侧任务栏立即显示新任务并跳转详情页`：验证新 task 进入 recent tasks 后以英文 status / stage 显示；首页不再额外轮询刷新 summary。
- `主题切换仍在任务工作台顶部生效`：验证顶部英文主题按钮仍同步 `html[data-theme]` 和 localStorage。
