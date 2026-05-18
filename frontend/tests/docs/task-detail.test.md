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
  -> 左侧任务栏打开时自动关闭字段 Progress；左侧任务栏关闭时自动显示字段 Progress
  -> 字段 Progress 是靠中间的右侧竖栏，按 Review、Reject、Accept 三组展示紧凑字段列表
  -> 字段 Progress 不承载字段展开区；点击字段行会把完整值、route reason、evidence chip 和必要复核入口放到最右侧 Review
  -> 最右侧 Review 可由 Review toggle 打开空态，可由字段行打开字段详情，也可由 evidence:// 超链接打开 evidence tab
  -> Review evidence tabs 按 task_id 隔离，切换任务不会共享上一任务的 evidence tab
  -> Agent 流一次性渲染完整 reason 文本和工具摘要，不再提供自动播放、下一步、速度条或单步播放
  -> Agent reason 中的 `[文本](evidence://...)` 被点击时打开最右侧 evidence Review
  -> 关闭 evidence Review 不影响字段 Progress 的自动显示规则
  -> 中央 Agent 文字流和底部 composer 使用同一动态内容框；整页只有一个侧栏时内容框用 `小弹性留白 / 宽阅读列 / 小弹性留白` 让文字在 Agent 自己的框里居中且减少两侧空白，右侧同时有两个栏时切到满宽
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
- `任务详情默认显示左任务栏、Agent 工作区，不显示字段 Progress 或 evidence Review`：验证默认状态只有左侧任务栏和中间 Agent，字段 Progress 随左栏打开而关闭，evidence Review 只由超链接打开。
- `Agent 流直接显示完整文字和工具行，不再暴露 replay 播放控制`：验证详情页按 Codex 风格直接展示完整文字流和工具行，并移除自动播放、下一步、速度条、单步播放和可点击 tool replay 控件。
- `Agent 文字流和底部输入框在中间内容框内居中，单侧栏时动态补旁侧留白`：验证单侧栏状态下 Agent 自己的文字框和输入框使用较小左右弹性留白把宽阅读列居中，Field Progress 与 Review 同时出现时切换成满宽不额外留空。
- `关闭左任务栏后自动显示字段 Progress`：验证左栏关闭会自动打开字段 Progress，并按字段展示 status、route 和 route reason。
- `字段 Progress 只做紧凑列表，点击字段会在最右侧 Review 打开详情`：验证字段 Progress 不在自身下方渲染详情，点击字段后由最右侧 Review 承载字段完整值、route reason 和复核入口。
- `字段 Progress 按 review、reject、accept 分组展示`：验证字段列表按 Review、Reject、Accept 固定顺序分组，并用分组标题和分割线区隔不同 route。
- `Review toggle 打开最右侧 evidence Review 空态，不影响字段 Progress`：验证用户不点击字段或 evidence 链接时也能手动打开最右侧 Review，空态提示选择字段或 evidence 链接，且字段 Progress 仍保持显示。
- `点击 evidence 链接打开最右侧 Review，字段 Progress 和 evidence Review 是两个竖栏`：验证 evidence 链接驱动最右侧 Review 打开，且字段 Progress 与 evidence Review 分属两个竖栏。
- `不同 evidence 会在最右侧 Review 内打开 tab`：验证多个 evidence 链接在同一个 Review 竖栏内以 tab 形式并存，最后点击的 evidence 成为当前 tab。
- `evidence Review tabs 按 task 隔离，不同任务不共享 tab`：验证切换 task_id 后旧任务打开过的 evidence tab 不会出现在新任务的 Review 面板里。
- `打开左栏会自动关闭字段 Progress，但不会关闭最右侧 evidence Review`：验证左栏打开只影响字段 Progress，不关闭 evidence Review。
- `waiting_review 字段复核提交 revise_and_approve 并刷新最近任务`：验证普通文本字段提交 payload、刷新详情、回写 localStorage 最近任务。
- `enum 字段复核提交 tagged payload 而不是字符串`：验证 enum 结构化编辑器提交时保留 `{variant, value}`。
- `reject 字段只显示拒绝路由，不提供人工修改入口`：验证拒绝字段不可在前端绕过 route policy 修改。
- `failed 任务会展示 backend 返回的失败原因`：验证无 replay 的失败任务显示错误原因和 no replay 顶栏。
- `failed 但已有 replay 的任务仍展示 Agent 工作区`：验证后置流程失败但有 replay 数据时不退回空白页。
