# `upload-workbench.test.tsx`

这组测试覆盖前端上传工作台的第一版行为，使用注入的 `createTask` 和 `getTaskSummary` 函数隔离真实 backend。

## 测试链路

```text
用户在上传工作台选择一个或多个 PDF
  -> 顶部单个主题按钮可在 Codex Light/Dark 间切换
  -> 主题切换会写入 `agent-gate.theme`，并同步到 html[data-theme]
  -> 填写 task_type、task_spec JSON 和可选 metadata JSON
  -> 前端先校验 JSON 必须是 object
  -> 校验通过后用重复 files 字段组装 FormData
  -> 调用 createTask
  -> 创建成功后把任务写入右侧最近任务列表并显示处理中
  -> 调用 getTaskSummary 轮询任务结果
  -> summary 进入终态后右侧列表显示处理结果和 route/失败状态
```

## 测试函数

- `默认 task_spec 不预置字段`：验证上传工作台默认 JSON 只有空 `task_name` 和空 `fields`，不会把文明寝室或其他业务字段写死到前端。
- `默认 task_type 为空且不展示内置类型提示`：验证 `task_type` 输入框没有默认值，也没有看起来像默认任务类型的 placeholder。
- `上传工作台用一个按钮切换 Codex light/dark 主题`：验证上传工作台只提供一个主题按钮，点击后在 Light/Dark 间切换，同时更新 `html[data-theme]` 和 localStorage。
- `非法 task_spec 会阻止提交并提示 JSON object 错误`：验证 `task_spec` 不是合法 JSON object 时不会调用创建接口，并在界面显示明确错误。
- `合法 PDF 和 JSON 会构造 backend 需要的 FormData`：验证前端提交的 `FormData` 包含重复 `files`、`task_type`、`task_spec` 和 `metadata`，并在创建成功后回调新任务。
- `创建任务后右侧列表先显示处理中，轮询完成后显示处理结果`：验证 `createTask` 返回 `pending/uploaded` 后，工作台不会等待 pipeline 完成或跳转详情页，而是立即把任务加到右侧列表；随后 `getTaskSummary` 返回 `completed/accept` 时，列表更新为“处理结果”和 route。
- `启动时从 backend 任务列表加载数据库任务`：验证工作台挂载时会调用 backend 任务列表接口，把数据库中已有的任务同步到右侧最近任务栏，避免只显示当前浏览器 localStorage 里打开过的任务。
- `轮询旧任务完成时不会把它移动到最新任务上方`：验证连续创建任务时最新任务保持在列表顶部；旧任务后续轮询完成只更新自己的状态，不会因为状态刷新重新置顶。
- `能力边界会显示支持文件类型和 external task_spec 约束`：验证工作台会展示 backend 能力边界，提醒调用方必须显式传入 `task_spec`，标明支持多文件任务，并把前端提交接口说明为重复 `files` 字段而不是旧版单文件 `file` 字段。
