# `upload-workbench.test.tsx`

这组测试覆盖首页新的 Codex 式新任务界面。测试用注入的 `createTask`、`getTaskSummary` 和 `listTasks` 隔离真实 backend，只验证首页任务栏、居中新任务 composer 和 `task_spec` 提交流程的可观察行为。

## 测试链路

```text
用户打开 /
  -> 首页直接渲染 Codex New Chat 形态的新任务界面，不再显示旧上传工作台首屏
  -> 左侧任务栏从 backend GET /tasks 加载最近任务
  -> 中间区域显示居中的新任务标题和 composer，不展示正在执行的 Agent 文字流
  -> 用户关闭左侧任务栏时，新任务界面仍然不自动显示右侧 Progress 或 Review
  -> composer 通过纸夹按钮选择 PDF
  -> 用户把 task_spec JSON 粘贴到对话框
  -> 前端校验 task_spec 是 object 且 task_spec.task_name 非空
  -> 用 task_spec.task_name 作为 backend 需要的 task_type
  -> 用重复 files 字段和 task_spec 组装 FormData
  -> POST /tasks 创建任务
  -> 左侧任务栏立即显示处理中
  -> 轮询 GET /tasks/{task_id} 后更新为处理结果
```

## 测试函数

- `首页默认就是 Codex 式新任务界面，不再显示旧上传首屏`：验证首屏保留任务栏和居中新任务 composer，旧的“上传工作台/能力边界/task_type/metadata”界面以及执行态 Agent 文字流不存在。
- `New Chat 关闭左侧任务栏后不自动显示右侧 Progress`：验证新任务界面关闭左侧任务栏后只保留中央 composer，不弹出右侧进度栏。
- `启动时从 backend 任务列表加载左侧任务栏`：验证首页挂载后会从 backend 任务列表同步数据库任务到左侧任务栏。
- `task_spec composer 会用 task_name 作为 task_type 并提交 PDF files`：验证 composer 提交时从 `task_spec.task_name` 推导 `task_type`，并用重复 `files` 字段发送多个 PDF。
- `没有 PDF 或缺少 task_name 时不会创建任务`：验证创建任务前会拦截缺少 PDF 和缺少 `task_spec.task_name` 的输入。
- `创建任务后左侧任务栏先显示处理中，轮询完成后显示处理结果`：验证新任务先进入左侧任务栏，轮询拿到终态后更新 route。
- `主题切换仍在任务工作台顶部生效`：验证顶部单个主题按钮仍写入 `html[data-theme]` 和 localStorage。
