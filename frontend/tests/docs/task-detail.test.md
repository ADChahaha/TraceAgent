# `task-detail.test.tsx`

这组测试覆盖 QA-only 任务详情页。详情页不再读取 result/replay/trace/audit，而是用 task summary 加持久化 SSE 事件重建“用户问题、模型过程输出、工具阅读过程、inline evidence”和多轮输入状态，并保证运行中按钮、输入框和 QA 流区域使用英文 UI label；中间 Agent 面板不再显示单独的内部标题栏。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 只 GET /qa/tasks/{task_id}
  -> 详情响应中的 documents/source_selectors 作为右侧 review 文档数据
  -> TaskDetail 打开 GET /qa/tasks/{task_id}/events?after_seq=0
  -> agent.event(type=source_indexed) 会把 SSE 里的 source_selectors 立即合并到当前 summary；如果详情还缺 documents/display_html，再补一次 task detail
  -> 如果补详情返回的 stream seq 旧于当前 SSE，也只保留当前运行态/seq，不丢掉补回来的 documents/display_html
  -> message.created 变成右侧用户消息
  -> agent.event(type=model_message) 变成左侧 assistant 消息，并保留 Markdown evidence link；每个 turn 有 is_final=true 最终答案时，该 turn 最终答案之前的非 final 模型消息和 tool 调用会各自合并成默认折叠的 Process 块
  -> 点击 evidence link 后打开右侧 review 文档并高亮 source_selector 对应 DOM
  -> range evidence 会把 `evidence://range/{start}/{end}` 展开成范围内多个 source_selector，并同时高亮多个 DOM
  -> 文件夹级 evidence 如果没有直接 source_selector，则定位到 header 自己，不跳到下面的第一个子节点
  -> 旧任务缺少文件夹级 source_selector 时，可用 evidence 链接文本匹配同名 heading 作为兼容定位
  -> 右侧 review 顶部只显示各级 folder/header breadcrumb，不显示文档文件名、evidence label 或 tool 动作文案
  -> table row evidence 会把 `/R001` 解析成具体 `<tr>`，不只高亮整张 table
  -> 同一源文档内切换 evidence 时复用 iframe srcDoc，只在 iframe DOM 内移动 current marker 并 smooth scroll 到新目标
  -> 如果 display_html 自带 page-like 纸张框，前端会在 iframe 里把 page 容器重排成连续 reading preview，并统一标题、段落和表格的 DOCX-like 阅读样式
  -> 右侧 review panel 用独立 resize separator 调整宽度，Agent 对话列按当前 Agent slot 宽度计算中心列和左右 blank，不能用 viewport 或侧栏宽度额外偏移内容列
  -> agent.event(type=tool_completed/tool_failed) 变成 Codex 式轻量可折叠工具过程行，摘要按钮带开关箭头，展开明细和摘要左边缘对齐；连续 tool 默认摘要只显示动作统计，展开工具组后每个 tool 仍默认折叠，单个有结果的 tool 也可展开；点击 tool 行只展开/收起结果，带 locator 的 read/inspect 通过右侧小按钮打开原文；展开后在动作行下用带边框的结果框承载 Markdown renderer，grep 在 tool 文案里显示搜索词并只显示前 3 条 preview，read 在 tool 文案里显示 locator 所属的各级 folder/header 链后再渲染正文，tree 显示清理后的目录文本，inspect 显示细粒度证据文本；渲染前会剥掉 document/section/locator、tree locator、tree 里的 .md/.list/.table 细碎节点、kind/title/columns/showing、block 注释、表格 row/R001 列以及 R001/[I001] 这类内部 selector，失败工具调用也使用普通工具行颜色
  -> Agent 对话流在用户接近底部时跟随 SSE 新消息；用户滚到历史位置阅读时，后续新消息不改写当前滚动位置
  -> turn.completed / turn.cancelled / turn.failed 清理运行态，让稳定的 composer handler 重新允许提交下一轮
  -> cancel 后如果 backend 已经把 summary 恢复为 ready/idle，前端也会根据最新 summary 解除本地 running/cancelling 锁定，避免按钮滞留在 Pause 态
  -> 用户追问时 POST /qa/tasks/{task_id}/inputs
  -> 追问 composer Enter 直接提交，Shift+Enter 在问题里保留换行
  -> 追问提交后先插入 optimistic 用户消息、清空 composer，并在 assistant 侧追加 Codex 式上下跳动 Thinking
  -> 重复提交相同文本时，只有 optimistic 和对应 backend 确认会合并，不会吞掉历史里同内容的用户消息
  -> 追问提交后立刻按当前 seq 重新连接 SSE，不等待 `/inputs` 返回；EventSource error 不主动 close，交给浏览器自动重连
  -> 左侧任务栏默认宽度是 224px，可通过 resize separator 拖拽或键盘调整
  -> 运行中不启动定时轮询刷新 summary；状态变化由 SSE 事件驱动，终态事件后只做一次详情刷新
  -> 运行中 textarea 保持可输入以保留下一轮草稿，placeholder 不随 running 状态改写；composer 右下角只有一个固定主操作按钮，running/ready 不会追加第二个按钮，也不会改写主按钮 DOM、属性、class 和尺寸；空闲时同一个按钮显示 Send 并提交，running 时同一个按钮显示 Pause 并 POST /qa/tasks/{task_id}/cancel
```

## 测试函数

- `loadTaskDetail 只读取 QA task summary，不再请求 result/replay/trace/audit`：验证详情聚合函数只请求 QA task 详情端点，其余旧详情数据为 `null`，并保留该端点返回的 `documents/source_selectors`。
- `QA API 会提交输入、取消 active turn，并生成可续传事件 URL`：验证输入、取消和 events URL 都指向 `/api/backend/qa/tasks/*`。
- `任务详情会从 QA 事件流重建用户问题、模型回答和 inline evidence`：验证 SSE 中的 user message 和 model_message 会进入 Agent 流，且 evidence 链接保持可点击 href。
- `点击 inline evidence 会用现有任务详情数据打开右侧 review 文档`：验证 evidence link 不请求旧 replay 或新 review 端点，而是使用现有 `GET /qa/tasks/{task_id}` 响应里的 `display_html/source_selectors` 打开右侧 review 文档并高亮证据，右侧 review 保持在主界面右栏。
- `右侧 review 顶部只显示 folder scope，不显示文件名和 tool 动作文案`：验证打开右侧 review 后，顶部 bar 只显示当前 evidence 所属的各级 folder/header，不显示文档文件名，也不会把 `Read paragraph in ...` 这类 tool 动作文案带进去。
- `旧 display_html 里的 paragraph title metadata 不会被当成 review scope`：验证旧任务中已经持久化的 `<p data-type="title">` 不会被当成 header，review breadcrumb 只使用真正的 h1-h6 heading。
- `首轮生成中收到 source_indexed 后可以立刻打开右侧 review 文档`：验证第一轮回答还在生成时，前端会直接消费 SSE 中的 `source_selectors`，不必等 turn 终态刷新就能点击 model message 的 evidence link 打开右侧 review。
- `首轮 source_indexed 触发的旧 seq 详情刷新仍会补齐 review 文档`：验证首轮 SSE 已经推进到更新 seq 时，后续 GET task detail 即使带着较旧的 `stream.last_event_seq`，前端也会合并其中的 `documents/display_html`，让刚出现的 evidence link 可以打开右侧 review。
- `右侧 review 会压平文档页面外框，只保留正文排版`：验证前端会把 display_html 里自带的 page 式背景、阴影和内边距去掉，避免 review 里再出现一层纸张框。
- `右侧 review panel 支持拖拽调整宽度，并保持 Agent 对话列左右空白对称`：验证 review panel 默认宽度、拖拽和键盘调宽逻辑，以及单开左侧任务栏或左右栏同时打开时，Agent 对话列都按当前 Agent slot 宽度计算中心列和左右 blank，不再注入 viewport 或侧栏宽度偏移变量。
- `文件夹级 inline evidence 会定位到对应 header 而不是子节点`：验证 `evidence://0001.0001` 这类目录级链接即使没有直接 selector，也会定位到同名 header DOM id，并明确不高亮下面的正文子节点。
- `旧 source_selectors 缺少文件夹映射时会用链接文本定位 header`：验证老任务没有 folder selector 时，前端只会用链接文本匹配同名 heading，不会退到正文子节点。
- `切换同一文档内的 inline evidence 会在 iframe 内平滑跳转并移动高亮`：验证第二次点击同一文档的不同 evidence 时不会重写 iframe `srcdoc` 导致回到顶部，而是移除旧 marker、设置新 marker，并调用 smooth `scrollIntoView`。
- `右侧 review 会把 PDF 页面外框重排成 DOCX-like 连续阅读预览`：验证右侧 iframe wrapper 会把 PDF/MinerU 的 `.page` 纸张容器改为连续 reading preview，并注入 DOCX-like 的 main 宽度、留白和表格排版。
- `range evidence 会在右侧 review 同时高亮范围内多个节点并滚到起始节点`：验证 `evidence://range/start/end` 会按 `source_selectors` 同时高亮范围内多个节点，排除范围外节点，并滚动到起始节点。
- `表格 row evidence 会定位到具体表格行而不是整张表`：验证 `evidence://.../R001` 会优先高亮 table 内对应数据行 `<tr>`，而不是只高亮 `source_selectors` 指向的父 table。
- `任务详情不显示 Agent 面板内部标题栏`：验证中间 Agent 面板只保留对话流，不再显示 `Document QA` 和内部 `ready/running` 小状态。
- `任务详情左侧任务栏默认宽度和首页一致，并支持键盘调整`：验证详情页任务栏和首页一样默认 224px，范围是 176-360px，并能通过键盘和拖拽调整。
- `任务详情会显示工具阅读过程并在 turn 完成后恢复可追问状态`：验证工具事件显示为阅读过程，终态 turn 事件后稳定主按钮仍可作为下一轮入口。
- `单个 tree 工具调用也可以展开查看 Markdown 渲染后的目录结果`：验证只有一个 `tree` 工具事件时也会显示独立的展开按钮，默认只显示 `Viewed outline`，展开后显示 Markdown code block 里的目录结果。
- `read 工具文案会从正文块所属 section 解析最近 folder`：验证 read locator 只映射到 table/p 这类正文块、父级 folder selector 缺失时，前端会沿 display_html 里的 section/aria-labelledby 找最近 header，并显示为 `Read evidence in ...`。
- `read range 工具文案会用完整 folder 层级而不是 range 字面量`：验证 range locator 不会直接显示 `evidence://range/...`，而是把起始 path 所属的多级 folder/header 拼成可读链路。
- `read 工具文案会显示所属 folder 的完整层级`：验证普通 read locator 指向正文块时，工具行显示从上级 section 到下级 section 的完整 folder/header 链，例如 `Read paragraph in 3．出願手続 / 4）選考料`。
- `运行中任务详情不启动定时轮询刷新 summary`：验证 active turn 期间详情页不会启动 `setInterval` 反复 GET summary，避免刷新打断用户输入。
- `运行中的 SSE 更新不会禁用正在输入的追问草稿`：验证 SSE 把 task 更新为 running 时，textarea 仍保持可编辑且保留当前草稿。
- `用户不在底部时 SSE 新消息不会强制滚到最底部`：验证用户已把 Agent 对话流滚到历史位置时，后续 SSE 新消息只追加内容，不覆盖当前 `scrollTop`。
- `运行状态变化不会改变 composer 单按钮结构和按钮外观`：验证 SSE 事件切到 running 时输入框 placeholder 保持稳定，composer 不出现 `Send question` / `Pause answer` 两个 sibling，只保留同一个固定主按钮，且不改写 `disabled`、`aria-disabled` 或 class；按钮内 Send/Pause icon 都常驻，只切 `data-visible`。
- `追问会复用同一个 task 提交下一轮输入`：验证底部 composer 用同一个 `task_id` 调 `/inputs`，提交后立即清空英文输入框并把用户消息推到对话流上方。
- `追问 composer 用 Enter 提交问题，Shift Enter 保留换行`：验证任务详情 composer 的键盘语义，Shift+Enter 只插入换行，Enter 才提交多行追问。
- `追问提交后会立即显示重复用户消息并追加 Thinking 状态`：验证用户再次提交与历史相同的问题时，新用户消息不会被去重吞掉，并且 assistant 侧立即显示 `Thinking`，主操作按钮保持稳定。
- `追问提交后会立即按当前 seq 重新连接 SSE，不等待输入请求返回`：验证提交追问后前端马上用当前事件游标重建 EventSource，避免必须刷新页面才看到新 turn 事件。
- `SSE error 不主动关闭事件源，避免空闲连接断开后只能刷新恢复`：验证 EventSource 报错时前端不调用 `close()`，保留浏览器原生自动重连能力。
- `Thinking 使用 Codex 式跳动指示器，不渲染问号或 spinner`：验证运行中的 assistant 占位使用上下跳动点，不显示问号或旋转加载图标。
- `QA 对话使用左右布局，用户消息在右侧，assistant 消息在左侧且不显示角色标签`：验证消息通过位置区分说话方，不在气泡里显示 `You` 或 `AI`。
- `最终答案出来后会把同一 turn 的过程默认折叠`：验证 `is_final=true` 最终答案直接显示，而同一 turn 中更早的非 final 模型消息和 tool 调用默认收进 `Process` 折叠块，用户展开后才看到过程和折叠的 tool 行。
- `每一轮对话都会各自折叠过程`：验证多轮 SSE 里每个带最终答案的 turn 都生成自己的 `Process` 折叠块；展开第一轮时只显示第一轮过程，第二轮过程仍保持折叠，直到用户打开第二个过程块。
- `连续工具事件会用 Codex 式轻量过程行默认折叠，并允许展开查看每个 tool`：验证连续工具调用默认只显示聚合计数摘要，摘要不写失败状态，摘要按钮有开关箭头；展开工具组后每个 tool 仍默认折叠，点击 `Viewed outline`、`Searched 出願期間`、`Read paragraph in 出願受付期間`、`Inspected table row` 这类动作行才展开对应结果；带 locator 的 read/inspect 行右侧会出现小按钮，点击它才打开右侧 review 原文；结果框中展示 Markdown 渲染后的可核对内容：grep 在 tool 文案里显示搜索词，只显示前 3 条命中 preview 和剩余数量，不显示 document/section metadata；read 在 tool 文案里显示 locator 所属的 folder/header 链，而不是使用正文 metadata title，再剥掉 `kind/locator/title/rows/columns/showing`、`<!-- block evidence://... -->`、表格里的 `row/R001` 内部列和 list 里的 `[I001]` selector，把 Markdown 表格/列表渲染成真实内容；inspect 只显示证据文本，不显示 selector metadata；tree 以 Markdown 代码块显示清洗后的目录树文本，只保留原始行尾带 `/` 的目录节点，去掉 `evidence://...` 前缀并过滤 `.md/.list/.table` 细碎节点；失败工具调用不加红色失败 class；`inspect` 使用独立图标，同一组追加新 tool 时保持已展开状态。
- `运行中点击稳定单按钮会调用 cancel`：验证 active turn 时固定主操作按钮点击会调用 cancel API。
- `cancel 成功并刷新为 ready 后会解除 running 锁定`：验证 cancel 后如果 task summary 已经回到 ready/idle，前端会释放本地 running/cancelling 状态并把固定主按钮恢复成 Send。
