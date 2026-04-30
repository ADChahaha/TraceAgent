# `task-detail.test.tsx`

这组测试覆盖任务详情页中人工复核的主路径，使用注入的加载和提交函数隔离真实 backend。

## 测试链路

```text
任务详情页接收 task_id
  -> 调用 loadTaskDetail 读取 summary/result/trace/review/audit
  -> failed summary 带 error_message 时在页面顶部展示失败原因
  -> 先从 result/review 字段中建立 field_name 到 display_name 的动态映射
  -> trace tab 展示 document_processor、file_extraction_agent、route_policy_agent 的执行过程
  -> trace tab 从 agent_trace 中读取 document_processor 返回的完整 markdown，并在原始 Markdown 区域直接展示
  -> trace tab 额外展示 backend 返回的 agent_trace 原始调用记录摘要
  -> result/review/trace/audit 中的数组字段值按 list 条目分行展示
  -> file_extraction_agent 的字段决策过程同时出现在 trace、review 和 audit 视图
  -> 字段决策过程按 broad_extraction、field_resolution/tool、final_result、route_validation 展示
  -> broad_extraction 中的候选 blocks 用可折叠区域展示 markdown 正文，不展示 block_id
  -> field_resolution 中展示该阶段产出的 route 前 agent 字段名和值，并说明读取相关字段或执行 final_decision 等 action 的过程
  -> action 明细展示引用数量、document/page/span，不直接展示 block_id
  -> action refs 的 React key 使用 block_id/index 区分同页同 span 的不同表格行
  -> route_validation 单独展示 route policy 结论，避免把 agent final result 误读成验证结论
  -> waiting_review 时把字段证据放在默认收起的可折叠区域，展开后按受控 markdown 渲染，并展示动作、agent 决策过程和复核输入
  -> 用户从 trace tab 切回复核 tab
  -> 用户填写复核值和备注
  -> submitReview 提交 revise_and_approve
  -> 成功后重新加载任务详情
  -> 用刷新后的 summary 回写最近任务 localStorage 状态
```

## 测试函数

- `waiting_review 任务会展示证据并提交 revise_and_approve 后刷新详情`：验证复核页会把证据文本放进默认收起的可折叠区域，展开后把证据 markdown 渲染成标题、紧凑表格和加粗文本，不直接显示原始 markdown 标记；同时验证 review 和 trace 中能看到 file_extraction_agent 的字段决策、`broad_extraction -> field_resolution/tool -> final_result -> route_validation` 四段过程、候选 block 折叠 markdown 正文且不展示 block_id、route 前 resolution 输出、route policy 结论、search_grep、add_broad_candidate、final_decision 动作和 action refs 摘要，并能在 trace 中看到 `agent_trace` 的按序调用记录摘要；字段主文案使用 backend 返回的 `display_name`，提交 payload 仍按 backend 协议使用 `field_name`；复核刷新后会把最近任务缓存从 `waiting_review/review` 回写成 `completed/done`。
- `failed 任务会展示 backend 返回的失败原因`：验证 summary 中的 `error_message` 会在 failed 详情页顶部以“任务失败”提示展示，避免用户只能看到 `failed/done` 而不知道失败原因。
- `list 字段在结果页按条目分行展示`：验证 `agent_value` 和 `final_value` 是数组时，结果表会把每个条目渲染成独立 list item，不再显示压缩后的 JSON 数组字符串。
- `action refs 同页同 span 但 block 不同时不会触发重复 key warning`：验证 action refs 展示仍只把 document/page/span 给用户看，但渲染 key 会包含 block_id/index，避免同页同 span 的不同表格行触发 React 重复 key warning。
- `trace 会直接展示 document_processor 返回的完整原始 Markdown`：验证 trace tab 会从 `agent_trace[].response.markdown` 读取完整原始 markdown，并按文件直接显示在“原始 Markdown”区域，方便检查 OCR 和表格结构。
- `审计记录会展示字段提交对应的 agent 决策过程`：验证 audit tab 的字段提交记录下方会展示对应 agent 决策过程，包含动态字段显示名、最终定案原因和关键 action 明细，不把内部字段 key 当作主展示文案。
- `没有额外 tool/action 时不会把 resolution 显示成 skipped`：验证字段定案没有额外 action 时，详情页仍展示 resolution 步骤，显示“未记录额外 tool/action；resolution 直接将候选证据定案为字段输出。”和该阶段产出的 route 前字段值，不会把该阶段误标为 `skipped`。
