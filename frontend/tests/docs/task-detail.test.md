# `task-detail.test.tsx`

这组测试覆盖 QA-only 任务详情页。详情页不再读取 result/replay/trace/audit，而是用 task summary 加持久化 SSE 事件重建“用户问题、模型过程输出、工具阅读过程、inline evidence”和多轮输入状态，并保证运行中按钮、输入框和 QA 流区域使用英文 UI label；中间 Agent 面板不再显示单独的内部标题栏。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 只 GET /qa/tasks/{task_id}
  -> 详情响应中的 documents/source_selectors 作为右侧 review 文档数据
  -> TaskDetail 打开 GET /qa/tasks/{task_id}/events?after_seq=0
  -> message.created 变成右侧用户消息
  -> agent.event(type=model_message) 变成左侧 assistant 消息，并保留 Markdown evidence link
  -> 点击 evidence link 后打开右侧 review 文档并高亮 source_selector 对应 DOM
  -> range evidence 会把 `evidence://range/{start}/{end}` 展开成范围内多个 source_selector，并同时高亮多个 DOM
  -> 文件夹级 evidence 如果没有直接 source_selector，则定位到 header 自己，不跳到下面的第一个子节点
  -> 旧任务缺少文件夹级 source_selector 时，可用 evidence 链接文本匹配同名 heading 作为兼容定位
  -> table row evidence 会把 `/R001` 解析成具体 `<tr>`，不只高亮整张 table
  -> 同一源文档内切换 evidence 时复用 iframe srcDoc，只在 iframe DOM 内移动 current marker 并 smooth scroll 到新目标
  -> 右侧 review panel 用独立 resize separator 调整宽度，并让中间对话列按左右 panel 宽度补偿空白比例
  -> agent.event(type=tool_completed/tool_failed) 变成 Codex 式轻量可折叠工具过程行，摘要按钮带开关箭头，展开明细和摘要左边缘对齐；tool 文案只显示动作和内容类型，不展示具体 evidence/path/locator
  -> turn.completed / turn.cancelled / turn.failed 让 composer 从暂停按钮恢复成发送按钮
  -> 用户追问时 POST /qa/tasks/{task_id}/inputs
  -> 追问 composer Enter 直接提交，Shift+Enter 在问题里保留换行
  -> 追问提交后先插入 optimistic 用户消息、清空 composer，并在 assistant 侧追加 Codex 式上下跳动 Thinking
  -> 重复提交相同文本时，只有 optimistic 和对应 backend 确认会合并，不会吞掉历史里同内容的用户消息
  -> 追问提交后立刻按当前 seq 重新连接 SSE，不等待 `/inputs` 返回；EventSource error 不主动 close，交给浏览器自动重连
  -> 左侧任务栏默认宽度是 224px，可通过 resize separator 拖拽或键盘调整
  -> 运行中按钮从 `Send question` 切换为 `Pause answer`，点击后 POST /qa/tasks/{task_id}/cancel
```

## 测试函数

- `loadTaskDetail 只读取 QA task summary，不再请求 result/replay/trace/audit`：验证详情聚合函数只请求 QA task 详情端点，其余旧详情数据为 `null`，并保留该端点返回的 `documents/source_selectors`。
- `QA API 会提交输入、取消 active turn，并生成可续传事件 URL`：验证输入、取消和 events URL 都指向 `/api/backend/qa/tasks/*`。
- `任务详情会从 QA 事件流重建用户问题、模型回答和 inline evidence`：验证 SSE 中的 user message 和 model_message 会进入 Agent 流，且 evidence 链接保持可点击 href。
- `点击 inline evidence 会用现有任务详情数据打开右侧 review 文档`：验证 evidence link 不请求旧 replay 或新 review 端点，而是使用现有 `GET /qa/tasks/{task_id}` 响应里的 `display_html/source_selectors` 打开右侧 review 文档并高亮证据，右侧 review 保持在主界面右栏。
- `右侧 review panel 支持拖拽调整宽度，并让对话列按左右面板补偿居中`：验证 review panel 默认宽度、拖拽和键盘调宽逻辑，以及 Agent 对话列通过左右空白比例抵消 task sidebar 与 review panel 的视觉偏移。
- `文件夹级 inline evidence 会定位到对应 header 而不是子节点`：验证 `evidence://0001.0001` 这类目录级链接即使没有直接 selector，也会定位到同名 header DOM id，并明确不高亮下面的正文子节点。
- `旧 source_selectors 缺少文件夹映射时会用链接文本定位 header`：验证老任务没有 folder selector 时，前端只会用链接文本匹配同名 heading，不会退到正文子节点。
- `切换同一文档内的 inline evidence 会在 iframe 内平滑跳转并移动高亮`：验证第二次点击同一文档的不同 evidence 时不会重写 iframe `srcdoc` 导致回到顶部，而是移除旧 marker、设置新 marker，并调用 smooth `scrollIntoView`。
- `range evidence 会在右侧 review 同时高亮范围内多个节点并滚到起始节点`：验证 `evidence://range/start/end` 会按 `source_selectors` 同时高亮范围内多个节点，排除范围外节点，并滚动到起始节点。
- `表格 row evidence 会定位到具体表格行而不是整张表`：验证 `evidence://.../R001` 会优先高亮 table 内对应数据行 `<tr>`，而不是只高亮 `source_selectors` 指向的父 table。
- `任务详情不显示 Agent 面板内部标题栏`：验证中间 Agent 面板只保留对话流，不再显示 `Document QA` 和内部 `ready/running` 小状态。
- `任务详情左侧任务栏默认宽度和首页一致，并支持键盘调整`：验证详情页任务栏和首页一样默认 224px，范围是 176-360px，并能通过键盘和拖拽调整。
- `任务详情会显示工具阅读过程并在 turn 完成后恢复可追问状态`：验证工具事件显示为阅读过程，终态 turn 事件会让按钮回到 `Send question`。
- `追问会复用同一个 task 提交下一轮输入`：验证底部 composer 用同一个 `task_id` 调 `/inputs`，提交后立即清空英文输入框并把用户消息推到对话流上方。
- `追问 composer 用 Enter 提交问题，Shift Enter 保留换行`：验证任务详情 composer 的键盘语义，Shift+Enter 只插入换行，Enter 才提交多行追问。
- `追问提交后会立即显示重复用户消息并追加 Thinking 状态`：验证用户再次提交与历史相同的问题时，新用户消息不会被去重吞掉，并且 assistant 侧立即显示 `Thinking` 和暂停按钮。
- `追问提交后会立即按当前 seq 重新连接 SSE，不等待输入请求返回`：验证提交追问后前端马上用当前事件游标重建 EventSource，避免必须刷新页面才看到新 turn 事件。
- `SSE error 不主动关闭事件源，避免空闲连接断开后只能刷新恢复`：验证 EventSource 报错时前端不调用 `close()`，保留浏览器原生自动重连能力。
- `Thinking 使用 Codex 式跳动指示器，不渲染问号或 spinner`：验证运行中的 assistant 占位使用上下跳动点，不显示问号或旋转加载图标。
- `QA 对话使用左右布局，用户消息在右侧，assistant 消息在左侧且不显示角色标签`：验证消息通过位置区分说话方，不在气泡里显示 `You` 或 `AI`。
- `连续工具事件会用 Codex 式轻量过程行默认折叠，并允许展开查看每个 tool`：验证连续工具调用默认只显示聚合计数摘要，摘要不写失败状态，摘要按钮有开关箭头，展开后只显示 `Viewed outline`、`Read paragraph`、`Inspected table row` 这类动作和内容类型，不泄露具体 path/evidence；带 locator 的 read/inspect 行可点击打开右侧 review，`inspect` 使用独立图标，同一组追加新 tool 时保持已展开状态。
- `运行中发送按钮会切换为暂停按钮并调用 cancel`：验证 active turn 时按钮显示 `Pause answer`，点击调用 cancel API。
