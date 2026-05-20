# `task-detail.test.tsx`

这组测试覆盖任务详情页新的 Codex 式工作台契约。测试用注入的 `loadTaskDetail` 和 `listTasks` 隔离真实 backend，只验证前端可观察行为与 API payload。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 先读取 summary
  -> 只继续读取 result/replay/review，不主动读取 trace/audit；处理中任务即使 has_trace=false 也会尝试读取 replay，让原文 partial replay 能先显示
  -> 如果 summary 仍是 pending/processing 或 stream.state=running，TaskDetail 在进入或刷新详情页时固定用 after_seq=0 打开任务事件 EventSource，让 backend 从头重放当前任务事件
  -> TaskDetail 消费 backend SSE 的命名事件，例如 `task.stage_changed` 和 `agent.event`；事件 seq 只推进内部游标和 liveActions 去重，不会让每条 live event 重建 EventSource
  -> replay 尚未生成时仍显示常规 Agent 工作区和 `Thinking`，一旦 replay 可用就原地渲染 Agent 工作区，收到 `agent.event` 时只把非空 model_message 和 tool_completed/tool_failed 追加为 live tool/message；tool_started 不显示，source_indexed 只触发 detail 刷新；live action 再按 seq 和工具参数指纹与 replay.actions 去重
  -> TaskDetail 用 GET /tasks 与 localStorage 合并最近任务
  -> ReplayReview 默认渲染“左侧任务栏 + 中间 Agent”，全局顶栏只显示任务标题和最右侧 Review 图标按钮，不显示 `Review` tab 或当前文件名
  -> 左侧任务栏显示最近任务和“新任务”入口，只能由顶部左侧 toggle 手动开关
  -> 右侧 Review 工作栏由顶部最右侧图标按钮显式开关；关闭左侧任务栏不会自动显示右侧栏，证据链接和可定位工具行会自动打开右侧原文 tab
  -> replay.outline_tree 会进入独立 Contents 面板；它只负责结构导航和当前位置提示，不参与 Agent 阅读列的侧栏计数，避免压窄正文
  -> 字段 Progress 是靠中间的右侧竖栏，按字段名排序展示紧凑字段列表，不再分 Review / Reject / Accept 组
  -> 字段 Progress 不承载字段展开区；点击字段行只更新选中态，字段 summary 保留在 Progress 行里
  -> 右侧 Review 工作栏内默认有 `Review` tab；evidence:// 链接、read、add_candidate_evidence 会按文件打开或切换完整原文 tab，只在 replay.source_selectors 明确包含 path_id 时，用 replay.display_html 里的同名虚拟 path_id DOM id 定位高亮；如果 evidence 使用 `evidence://range/<start>/<end>`，则按 `start` 所属文件打开 tab，并把这段连续 block 一起高亮；当 range 两端是 section id 时，前端会把 section 范围下的连续可读 block 一起高亮
  -> evidence 或 range 打开原文后，会用起始 path_id 前缀匹配 replay.outline_tree 中最深节点，让 Contents 面板跟随选中对应结构，并把该节点滚到固定上方锚点，避免只变色但用户看不到当前位置
  -> Contents 节点点击会打开或切换右侧原文；普通 DOM id 直接高亮该结构节点，section id 则定位到 section 下第一个可读 block，并高亮该 section 下的连续可读 block
  -> 左侧 Agent evidence 链接、tool 行或 Contents 点击发起右侧 smooth scroll 时，右侧滚动过程中的可见 block 回传会保持暂停，防止相邻 block 反向覆盖用户刚点中或刚链接到的 Contents 节点；用户在右侧原文中 wheel、pointer、touch 或键盘滚动后才恢复右侧驱动左侧同步
  -> 同一个原文 tab 里连续点击 evidence 或 Contents 时，不重写 iframe 的 srcDoc；前端只在现有 iframe DOM 内替换高亮并重新发起定位请求，让 smooth scroll 从当前滚动位置出发
  -> 原文 tab 按 task_id 和文件隔离，tab 标题只显示解码后的 basename 文件名，不显示目录、URL 编码或 `%20`；同一文件内不同证据复用同一个文件 tab 并更新定位高亮；多文件才打开多个文件 tab；关闭原文 tab 后回到右侧 `Review`
  -> 原文查看器只显示完整原文渲染，不在 iframe 上方重复显示文件标题，并把原文内容铺满右侧框体，长表格、图片和长词按框宽收缩或换行，不出现左右滑动的纸张感
  -> Agent 流一次性渲染完整 model_message 文本和工具摘要，不再提供自动播放、下一步、速度条或单步播放
  -> live tool/message 追加时按用户当前位置决定是否滚动：用户在底部就继续跟随到底部，用户离开底部阅读旧内容就保持当前位置；空 `model_message` 不显示为 `Thinking` 或工具行
  -> Agent 工具行只展示真实可见工具：tree/read/add_candidate_evidence/review_evidences/write_field，submit_result 作为收尾动作不进入文字流
  -> 非空 model_message 文字段作为 tool run 边界；文字后连续出现多个 tool 时，整组默认折叠成一个 tool group 并保留在原始时间线位置，用户展开后才显示每个工具明细；只有单个 tool 时才直出，旧 tool.reason 不进入文字流
  -> tool group 折叠态显示一条类似 Codex 的自然语言摘要，概括这一段做了什么、涉及多少个文件/证据/字段，不再拼接工具动作摘要
  -> 工具行使用短英文动作摘要和轻量语义图标：ListTree、BookUser、BookmarkPlus、FileCheck、PenLine；tree 只显示 Viewed outline，read 只显示 Read passage，submit_result 不进入文字流
  -> Agent model_message 中的 `[文本](evidence://...)` 被点击时打开右侧对应文件的完整原文 tab，路径式 selector 和点号 locator 都会跳到对应原文节点并高亮，不替换中央 Agent 工作区
  -> Agent model_message 使用受控 Markdown 渲染段落、列表、加粗、行内 code 和 evidence 链接，让模型输出的阅读地图可以直接给用户看
  -> 切回或关闭原文 tab 后，右侧 `Review` 在已打开的右侧栏内恢复字段 Progress
  -> 中央 Agent 文字流和底部 composer 使用同一动态内容框；整页没有侧栏或只有一个侧栏时内容框用 `弹性留白 / 阅读列 / 弹性留白`，中间区变窄时先连续压缩两侧留白，留白归零后才压缩阅读列本身
  -> 中间 Agent 区底部保留对话输入框，左下角加文件，右下角发送
  -> 字段写入区只合并 result.fields 和 replay 里的 visible write_field / set_field actions
  -> enum tagged payload 仍按 `{variant, value}` 结构展示，但不再提供人工编辑
  -> 没有任何人工提交入口，字段详情只读
  -> failed summary 展示 backend error_message；如果 failed 任务仍有 replay，则继续显示 Agent 工作区
```

## 测试函数

- `loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit`：验证详情聚合函数只请求 summary、result 和 replay，并把 `trace/audit` 留成 `null`。
- `loadTaskDetail 在处理中也拉 replay 以便实时显示原文`：验证 running/pending/processing 任务即使 `has_trace=false` 也会请求 replay，这样 document_processor 已产出的原文 HTML 可以先进入右侧原文 tab。
- `低层 API 仍保留 trace 和 audit 读取能力`：验证 `getTaskTrace` 与 `getTaskAudit` 仍可单独读取，详情页收口不等于删除底层 API 适配。
- `任务详情默认显示左任务栏、Agent 工作区，不在全局顶栏显示 Review tab`：验证默认状态只有左侧任务栏和中间 Agent，全局顶栏保留任务栏按钮、任务标题、状态和最右侧 Review 图标按钮，不渲染 `Review` tab、当前文件名或右侧工作栏。
- `关闭左栏且未打开右栏时，Agent 仍保持居中内容框`：验证用户只关闭左侧任务栏时不会自动打开右侧 Review，Agent 在没有侧栏时仍使用居中阅读列，不再靠左铺满。
- `Agent 流直接显示完整文字和工具行，不再暴露 replay 播放控制`：验证详情页按 Codex 风格直接展示完整文字流和工具行，并移除自动播放、下一步、速度条、单步播放和可点击 tool replay 控件。
- `Agent 工具行按真实工具显示英文摘要和语义图标`：验证连续无文字工具默认折叠，折叠态显示类似 Codex 的自然语言摘要，展开后 tree/read/add_candidate_evidence/review_evidences/write_field 使用约定的英文文案和图标标识，且 tree 只显示 `Viewed outline`、read 只显示 `Read passage`，不再显示 `submit_result`。
- `单个 tool 保持直出，不会折叠成 group`：验证只有一条 tool 时不会被包进折叠容器，仍然以普通 tool 行直接显示。
- `tool action 的旧 reason 字段不进入 Agent 文字流`：验证旧 replay 里残留的 tool.reason 不会渲染成可见文字，工具行仍按 args/result 展示。
- `Agent 文字后的连续多个 tool 整组折叠，不先直出第一条 tool`：验证文字段后的 tool run 如果包含多条 tool，第一条 tool 不会先直出，而是和后续 tool 一起进入折叠组；下一段文字会重新开始新的 tool run，单个 tool 仍保持直出。
- `终态 replay 保留文字和 tool group 的原始时间线位置`：验证终态 replay 已经带有 model_message/tool 交错时间线时，前端仍把连续工具折叠在两段文字之间，不把工具组集中挪到文字上方。
- `顶部最右侧 Review 按钮打开右侧字段 Progress，字段列表只按字段排序`：验证右上角 Review 图标按钮在不改变左栏状态的情况下显式打开右侧 Review 工作栏，展示字段 Progress，并可再次点击关闭。
- `字段 Progress 显示字段摘要，点击字段不会占用 Review 工作区`：验证字段 summary 留在 Progress 行里，点击字段只改变选中态，不打开 Inspector 或固定子 tab。
- `点击 evidence 链接会打开顶层原文 tab，并定位高亮对应位置`：验证 evidence:// 链接会在右侧 Review 工作栏打开对应文件的完整原文 tab，渲染 replay.display_html 的全文，用 smooth scroll 跳到对应原文节点并高亮，同时不展示字段值、证据文本、原文位置或内部 evidence URI 等实现字段，并保留中央 Agent 工作区。
- `Agent model_message 用受控 Markdown 渲染面向用户的 outline`：验证模型输出的阅读地图会在 Agent 流里渲染成 Markdown 列表、加粗和行内 code，同时其中的标准 evidence 链接仍能打开右侧原文并高亮对应 block。
- `点击连续 block range evidence 链接会打开原文并高亮整段连续 block`：验证 `evidence://range/<start>/<end>` 会按 `start` 所属文件打开原文 tab，把 `start` 作为滚动定位点，并同时高亮这段连续 block。
- `点击 section-level range evidence 链接会高亮该 section range 下的连续可读 block`：验证 range 两端如果是同一文档内的 section id，前端会从 `source_selectors` 找到落在这些 section 下的连续可读 block，并一起高亮，范围外 block 不被误选。
- `点击 evidence 后 Contents 会选中对应 outline 节点并滚到固定锚点`：验证点击 range evidence 后，前端会用起始 block 的 path_id 前缀匹配 outline_tree，把 Contents 中对应节点标成 active，并把该节点滚到固定上方锚点。
- `点击 Contents 节点会打开右侧原文并定位到对应结构位置`：验证 Contents 中普通结构节点点击后会打开右侧文件 tab，并直接高亮 replay HTML 中同 id 的结构节点。
- `点击 Contents section 节点会定位到该 section 下第一个可读 block`：验证 Contents 中 section id 没有同名 DOM 节点时，会从 source_selectors 找到该 section 下的连续可读 block，以第一个 block 作为定位点并高亮整段。
- `Contents 点击发起导航时不会被右侧滚动同步立刻覆盖`：验证点击 Contents 中靠近当前原文位置的节点后，右侧滚动同步不会马上把左侧 active 改回滚动途中看到的相邻节点。
- `Agent evidence 链接发起导航时不会被右侧滚动同步立刻覆盖`：验证点击 Agent 文本中的 evidence 链接后，右侧滚动同步不会马上把 Contents active 改回滚动途中看到的相邻节点。
- `右侧手动滚动后会恢复 Contents 跟随原文`：验证左侧发起导航后，用户在右侧原文中手动滚动会解除同步锁，让 Contents 重新按右侧当前可见 block 更新。
- `原文文件 tab 只显示解码后的文件名，原文内容上方不再重复文件标题`：验证带目录的文件名只在右侧 tab 显示解码后的 basename，`%20` 会显示成空格，并且原文 iframe 上方不再额外渲染重复标题栏。
- `点号 evidence URI 会打开原文文件 tab 并映射到真实 DOM 位置`：验证真实任务里的 `evidence://0001.0000.0009` 这类 locator 会先查 replay 里的 `source_selectors`，再高亮 replay HTML 里同名虚拟 path_id DOM 节点，打开同一份原文文件 tab。
- `0001.0019.0001 这类 base locator 会按实际段落定位，不会错配成旧 DOM id`：验证当工具文本不能直接匹配时，前端只依赖 replay.source_selectors 和同名虚拟 path_id DOM id，不沿用旧的点号编号或 `p001_b019` 猜测。
- `旧 replay 没有 source_selectors 时，evidence 链接只打开原文，不猜测 DOM 高亮位置`：验证没有映射表的旧 replay 只打开原文文件 tab，不做文本兜底、DOM id 兜底或 quote `<mark>` 高亮。
- `同一文件内不同 evidence 复用同一个原文文件 tab，只更新定位高亮`：验证同一文件内多个 evidence 链接只保留一个文件 tab，第二次点击只切换该 tab 的高亮节点，关闭后回到 `Review` 并显示字段 Progress。
- `同一原文 tab 内连续点击不同 evidence 不重写 iframe srcDoc`：验证同一个原文 tab 里第二次点击只更新现有 iframe DOM 的高亮和定位状态，不通过改写 `srcDoc` 触发 iframe 从顶部重新加载。
- `重复点击同一个 Contents 节点也会刷新右侧定位请求`：验证即使目标 selector 没变，重复点击 Contents 仍会更新 navigation key，让右侧原文重新执行定位。
- `不同文件的 evidence 才会打开不同原文文件 tab`：验证不同文件定位会打开不同文件 tab，并把最后点击的文件 tab 设为当前 tab。
- `右侧原文栏可以拉伸到更宽，便于查看完整文件`：验证 Contents 和右侧 Review/原文栏使用不同的 resize 语义，其中 Contents 有自己的宽度上限，右侧 Review/原文栏仍保留更大的 resize 上限，便于查看完整文件。
- `完整原文 tab 填满右侧框体，不再强制固定纸面宽度或横向滚动`：验证 iframe 里的原文内容按右侧框体 100% 宽度渲染，去掉灰底、外层留白、圆角和阴影，表格、媒体、长词和预格式文本都收进框内，不再保留 980px 纸面宽度和横向滚动条。
- `点击 read 和 add_candidate_evidence 工具行会打开对应顶层原文 tab`：验证 read 和 add_candidate_evidence 工具行本身是带 evidence href 的链接式控件，并复用 evidence 定位在右侧打开对应文件的完整原文 tab，跳到对应原文节点并高亮。
- `failed 任务会展示 backend 返回的失败原因`：验证无 replay 的失败任务显示错误原因和 no replay 顶栏。
- `failed 但已有 replay 的任务仍展示 Agent 工作区`：验证后置流程失败但有 replay 数据时不退回空白页。
- `处理中任务详情先显示常规对话工作台和 Thinking，再自动刷新到 replay`：验证任务详情页进入运行中任务时不显示“正在处理任务...”占位，而是显示常规 Agent 工作区和 `Thinking`，并用轮询兜底刷新到 replay/result 可用。
- `处理中任务详情会消费事件流并实时追加 Agent 工具输出`：验证任务详情页会监听 backend 真实 SSE 命名事件，收到 `agent.event` 后实时追加工具输出，同时阶段事件和 live event 都不会导致 EventSource 逐条重建。
- `刷新从头回放时不把同一工具的 start、completed 和 replay action 重复显示`：验证刷新后 SSE 从 0 重放时，前端不会把同一工具在 partial replay、tool_started 和 tool_completed 中显示成多条，只保留一条可见工具记录。
- `空 model_message 不渲染成 Thinking 工具行，前后工具继续按组折叠`：验证 backend SSE 里的空内容 model_message 会被丢弃，不占用文字段，也不会作为 `model_message` 工具混入 tool group；后续连续工具仍按真实工具数量折叠。
- `处理中 source_indexed 事件会刷新出原文 replay`：验证 live source index 到达后，TaskDetail 会刷新 partial replay，使运行中的任务也能拿到原文 HTML 和 selector 映射。
- `实时追加工具输出时，用户不在底部就保持当前阅读位置`：验证 live tool 增加时，如果用户已经离开底部阅读旧内容，Agent 文字流不会改写当前 `scrollTop`。
- `实时追加工具输出时，用户在底部就继续跟随到底部`：验证 live tool 增加时，如果用户追加前已经在底部，Agent 文字流会滚到新的底部。
- `处理中已有 replay 时，live read 工具行能打开原文并高亮`：验证 running 任务只要已有 partial replay 和 source_selectors，live read 工具行就能打开右侧原文 tab 并定位到同名虚拟 path_id DOM id。
- `已展开的 live tool group 追加新工具后保持展开`：验证用户手动展开的连续 tool group 在同一组里继续收到新的 live tool 时，不会因为组内工具数量变化而重新折叠。
