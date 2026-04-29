# `task-detail.test.tsx`

这组测试覆盖任务详情页中人工复核的主路径，使用注入的加载和提交函数隔离真实 backend。

## 测试链路

```text
任务详情页接收 task_id
  -> 调用 loadTaskDetail 读取 summary/result/trace/review/audit
  -> 先从 result/review 字段中建立 field_name 到 display_name 的动态映射
  -> trace tab 展示 document_processor、file_extraction_agent、route_policy_agent 的执行过程
  -> trace tab 额外展示 backend 返回的 agent_trace 原始调用记录摘要
  -> file_extraction_agent 的字段决策过程同时出现在 trace、review 和 audit 视图
  -> waiting_review 时把字段证据按受控 markdown 渲染，展示动作、agent 决策过程和复核输入
  -> 用户从 trace tab 切回复核 tab
  -> 用户填写复核值和备注
  -> submitReview 提交 revise_and_approve
  -> 成功后重新加载任务详情
  -> 用刷新后的 summary 回写最近任务 localStorage 状态
```

## 测试函数

- `waiting_review 任务会展示证据并提交 revise_and_approve 后刷新详情`：验证复核页会把证据 markdown 渲染成标题、紧凑表格和加粗文本，不直接显示原始 markdown 标记；同时验证 review 和 trace 中能看到 file_extraction_agent 的字段决策、field reference、global lookup、validation rule 动作，并能在 trace 中看到 `agent_trace` 的按序调用记录摘要；字段主文案使用 backend 返回的 `display_name`，提交 payload 仍按 backend 协议使用 `field_name`；复核刷新后会把最近任务缓存从 `waiting_review/review` 回写成 `completed/done`。
- `审计记录会展示字段提交对应的 agent 决策过程`：验证 audit tab 的字段提交记录下方会展示对应 agent 决策过程，包含动态字段显示名、最终定案原因和关键 action 明细，不把内部字段 key 当作主展示文案。
