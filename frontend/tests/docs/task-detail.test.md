# `task-detail.test.tsx`

这组测试覆盖任务详情页新的 Codex 式工作台契约。测试用注入的 `loadTaskDetail`、`listTasks` 和 `submitReview` 隔离真实 backend，只验证前端可观察行为与 API payload。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 先读取 summary
  -> 只继续读取 result/replay/review，不主动读取 trace/audit
  -> TaskDetail 用 GET /tasks 与 localStorage 合并最近任务
  -> ReplayReview 默认渲染“左侧任务栏 + 中间 Agent”
  -> 左侧任务栏显示最近任务和“新任务”入口，只能由顶部左侧 toggle 手动开关
  -> 左侧任务栏打开时不显示 Progress
  -> 用户关闭左侧任务栏后，右侧显示当前任务 Progress
  -> Agent reason 中的 `[文本](evidence://...)` 被点击时打开右侧 Review
  -> Review 打开时遮住 Progress；左侧任务栏和 Review 可以共存
  -> 关闭 Review 后，根据左侧任务栏开关状态恢复为“左栏 + Agent”或“Agent + Progress”
  -> 中间 Agent 区底部保留对话输入框，左下角加文件，右下角发送
  -> 字段写入区合并 result.fields 与 review.fields
  -> route=review 且 needs_review=true 时允许提交 revise_and_approve
  -> enum tagged payload 复核时保持 `{variant, value}` 结构
  -> route=reject 字段只展示拒绝结论，不提供人工修改入口
  -> failed summary 展示 backend error_message；如果 failed 任务仍有 replay，则继续显示 Agent 工作区
```

## 测试函数

- `loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit`：验证详情聚合函数只请求 summary、result、replay 和 waiting_review 时的 review handoff，并把 `trace/audit` 留成 `null`。
- `低层 API 仍保留 trace 和 audit 读取能力`：验证 `getTaskTrace` 与 `getTaskAudit` 仍可单独读取，详情页收口不等于删除底层 API 适配。
- `任务详情默认显示左任务栏和 Agent 工作区，不显示 Progress`：验证默认布局是左侧任务栏、中间 Agent、底部对话框，且不会同时展示右侧 Progress。
- `关闭左任务栏后显示 Progress，重新打开左栏后隐藏 Progress`：验证 Progress 只在左栏关闭且没有 Review 时出现，并展示 stream 游标。
- `点击 evidence 链接打开右侧 Review，Review 遮住 Progress 并可与左栏共存`：验证 evidence 链接驱动 Review 打开，Review 与 Progress 互斥，且重新打开左栏不会关闭 Review。
- `关闭 Review 后按左栏状态恢复 Progress 或仅保留左栏 Agent`：验证 Review 关闭后的恢复逻辑由左侧任务栏状态决定。
- `waiting_review 字段复核提交 revise_and_approve 并刷新最近任务`：验证普通文本字段提交 payload、刷新详情、回写 localStorage 最近任务。
- `enum 字段复核提交 tagged payload 而不是字符串`：验证 enum 结构化编辑器提交时保留 `{variant, value}`。
- `reject 字段只显示拒绝路由，不提供人工修改入口`：验证拒绝字段不可在前端绕过 route policy 修改。
- `failed 任务会展示 backend 返回的失败原因`：验证无 replay 的失败任务显示错误原因和 no replay 顶栏。
- `failed 但已有 replay 的任务仍展示 Agent 工作区`：验证后置流程失败但有 replay 数据时不退回空白页。
