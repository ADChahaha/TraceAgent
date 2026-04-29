# `upload-workbench.test.tsx`

这组测试覆盖前端上传工作台的第一版行为，使用注入的 `createTask` 函数隔离真实 backend。

## 测试链路

```text
用户在上传工作台选择一个或多个 PDF/DOCX
  -> 填写 task_type、task_spec JSON 和可选 metadata JSON
  -> 前端先校验 JSON 必须是 object
  -> 校验通过后用重复 files 字段组装 FormData
  -> 调用 createTask
  -> 创建成功后把任务交给 onCreated
```

## 测试函数

- `默认 task_spec 使用 scripts 里的文明寝室模板`：验证上传工作台默认 JSON 与 `agent/scripts/run_civilized_dormitory_extraction.py` 的文明寝室模板对齐，包含文档标题、楼栋、文明寝室房间号和文明寝室数量四个字段，以及脚本中的字段提示。
- `非法 task_spec 会阻止提交并提示 JSON object 错误`：验证 `task_spec` 不是合法 JSON object 时不会调用创建接口，并在界面显示明确错误。
- `合法 PDF/DOCX 和 JSON 会构造 backend 需要的 FormData`：验证前端提交的 `FormData` 包含重复 `files`、`task_type`、`task_spec` 和 `metadata`，并在创建成功后回调新任务。
- `能力边界会显示支持文件类型和 external task_spec 约束`：验证工作台会展示 backend 能力边界，提醒调用方必须显式传入 `task_spec`，标明支持多文件任务，并把前端提交接口说明为重复 `files` 字段而不是旧版单文件 `file` 字段。
