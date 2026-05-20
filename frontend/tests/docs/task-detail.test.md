# `task-detail.test.tsx`

这组测试覆盖任务详情页新的 Codex 式工作台契约。测试用注入的 `loadTaskDetail` 和 `listTasks` 隔离真实 backend，只验证前端可观察行为与 API payload。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 先读取 summary
  -> 只继续读取 result/replay/review，不主动读取 trace/audit
  -> TaskDetail 用 GET /tasks 与 localStorage 合并最近任务
  -> ReplayReview 默认渲染“左侧任务栏 + 中间 Agent”，全局顶栏只显示任务标题，不显示 `Review` tab 或当前文件名
  -> 左侧任务栏显示最近任务和“新任务”入口，只能由顶部左侧 toggle 手动开关
  -> 左侧任务栏打开时自动隐藏右侧 Review 工作栏；左侧任务栏关闭且停留在右侧 `Review` tab 时自动显示字段 Progress
  -> 字段 Progress 是靠中间的右侧竖栏，按字段名排序展示紧凑字段列表，不再分 Review / Reject / Accept 组
  -> 字段 Progress 不承载字段展开区；点击字段行只更新选中态，字段 summary 保留在 Progress 行里
  -> 右侧 Review 工作栏内默认有 `Review` tab；evidence:// 链接、read、add_candidate_evidence 会按文件打开或切换完整原文 tab
  -> 原文 tab 按 task_id 和文件隔离，tab 标题只显示解码后的 basename 文件名，不显示目录、URL 编码或 `%20`；同一文件内不同证据复用同一个文件 tab 并更新定位高亮；多文件才打开多个文件 tab；关闭原文 tab 后回到右侧 `Review`
  -> 原文查看器只显示完整原文渲染，不在 iframe 上方重复显示文件标题，并把原文内容铺满右侧框体，长表格、图片和长词按框宽收缩或换行，不出现左右滑动的纸张感
  -> Agent 流一次性渲染完整 reason 文本和工具摘要，不再提供自动播放、下一步、速度条或单步播放
  -> Agent 工具行只展示真实可见工具：tree/read/add_candidate_evidence/review_evidences/write_field，submit_result 作为收尾动作不进入文字流
  -> 带 reason 的文字段作为 tool run 边界；文字后连续出现多个 tool 时，整组默认折叠成一个 tool group，用户展开后才显示每个工具明细；只有单个 tool 时才直出
  -> tool group 折叠态显示一条类似 Codex 的自然语言摘要，概括这一段做了什么、涉及多少个文件/证据/字段，不再拼接工具动作摘要
  -> 工具行使用短英文动作摘要和轻量语义图标：ListTree、BookUser、BookmarkPlus、FileCheck、PenLine；tree 只显示 Viewed outline，read 只显示 Read passage，submit_result 不进入文字流
  -> Agent reason 中的 `[文本](evidence://...)` 被点击时打开右侧对应文件的完整原文 tab，路径式 selector 和点号 locator 都会跳到对应原文节点并高亮，不替换中央 Agent 工作区
  -> 切回或关闭原文 tab 后，右侧 `Review` 按左侧任务栏状态恢复字段 Progress
  -> 中央 Agent 文字流和底部 composer 使用同一动态内容框；整页只有一个侧栏时内容框用 `弹性留白 / 阅读列 / 弹性留白`，中间区变窄时先连续压缩两侧留白，留白归零后才压缩阅读列本身
  -> 中间 Agent 区底部保留对话输入框，左下角加文件，右下角发送
  -> 字段写入区只合并 result.fields 和 replay 里的 visible write_field / set_field actions
  -> enum tagged payload 仍按 `{variant, value}` 结构展示，但不再提供人工编辑
  -> 没有任何人工提交入口，字段详情只读
  -> failed summary 展示 backend error_message；如果 failed 任务仍有 replay，则继续显示 Agent 工作区
```

## 测试函数

- `loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit`：验证详情聚合函数只请求 summary、result 和 replay，并把 `trace/audit` 留成 `null`。
- `低层 API 仍保留 trace 和 audit 读取能力`：验证 `getTaskTrace` 与 `getTaskAudit` 仍可单独读取，详情页收口不等于删除底层 API 适配。
- `任务详情默认显示左任务栏、Agent 工作区，不在全局顶栏显示 Review tab`：验证默认状态只有左侧任务栏和中间 Agent，全局顶栏保留任务栏按钮、任务标题和状态，不渲染 `Review` tab、当前文件名或右侧工作栏。
- `Agent 流直接显示完整文字和工具行，不再暴露 replay 播放控制`：验证详情页按 Codex 风格直接展示完整文字流和工具行，并移除自动播放、下一步、速度条、单步播放和可点击 tool replay 控件。
- `Agent 工具行按真实工具显示英文摘要和语义图标`：验证连续无文字工具默认折叠，折叠态显示类似 Codex 的自然语言摘要，展开后 tree/read/add_candidate_evidence/review_evidences/write_field 使用约定的英文文案和图标标识，且 tree 只显示 `Viewed outline`、read 只显示 `Read passage`，不再显示 `submit_result`。
- `单个 tool 保持直出，不会折叠成 group`：验证只有一条 tool 时不会被包进折叠容器，仍然以普通 tool 行直接显示。
- `Agent 文字后的连续多个 tool 整组折叠，不先直出第一条 tool`：验证文字段后的 tool run 如果包含多条 tool，第一条 tool 不会先直出，而是和后续 tool 一起进入折叠组；下一段文字会重新开始新的 tool run，单个 tool 仍保持直出。
- `Agent 文字流和底部输入框在中间内容框内居中，单侧栏时动态补旁侧留白`：验证单侧栏状态下 Agent 自己的文字框和输入框用弹性左右留白把阅读列居中，宽度变小时先缩小留白再压缩阅读列；Field Progress 与 `Review` 同时出现时切换成满宽不额外留空。
- `关闭左任务栏后自动显示字段 Progress`：验证左栏关闭会自动打开字段 Progress，并按字段名排序展示 status、短值和 evidence 数量。
- `字段 Progress 显示字段摘要，点击字段不会占用 Review 工作区`：验证字段 summary 留在 Progress 行里，点击字段只改变选中态，不打开 Inspector 或固定子 tab。
- `点击 evidence 链接会打开顶层原文 tab，并定位高亮对应位置`：验证 evidence:// 链接会在右侧 Review 工作栏打开对应文件的完整原文 tab，渲染 replay.display_html 的全文，跳到对应原文节点并高亮，同时不展示字段值、证据文本、原文位置或内部 evidence URI 等实现字段，并保留中央 Agent 工作区。
- `原文文件 tab 只显示解码后的文件名，原文内容上方不再重复文件标题`：验证带目录的文件名只在右侧 tab 显示解码后的 basename，`%20` 会显示成空格，并且原文 iframe 上方不再额外渲染重复标题栏。
- `点号 evidence URI 会打开原文文件 tab 并映射到真实 DOM 位置`：验证真实任务里的 `evidence://0000.0001.0009` 这类 locator 会归一化到 `p001_b009`，打开同一份原文文件 tab 并高亮对应 DOM 节点。
- `同一文件内不同 evidence 复用同一个原文文件 tab，只更新定位高亮`：验证同一文件内多个 evidence 链接只保留一个文件 tab，第二次点击只切换该 tab 的高亮节点，关闭后回到 `Review` 并显示字段 Progress。
- `不同文件的 evidence 才会打开不同原文文件 tab`：验证不同文件定位会打开不同文件 tab，并把最后点击的文件 tab 设为当前 tab。
- `右侧原文栏可以拉伸到更宽，便于查看完整文件`：验证右侧 Review/原文栏的 resize 上限足够大，便于查看完整文件。
- `完整原文 tab 填满右侧框体，不再强制固定纸面宽度或横向滚动`：验证 iframe 里的原文内容按右侧框体 100% 宽度渲染，去掉灰底、外层留白、圆角和阴影，表格、媒体、长词和预格式文本都收进框内，不再保留 980px 纸面宽度和横向滚动条。
- `点击 read 和 add_candidate_evidence 工具行会打开对应顶层原文 tab`：验证 read 和 add_candidate_evidence 工具行本身是带 evidence href 的链接式控件，并复用 evidence 定位在右侧打开对应文件的完整原文 tab，跳到对应原文节点并高亮。
- `failed 任务会展示 backend 返回的失败原因`：验证无 replay 的失败任务显示错误原因和 no replay 顶栏。
- `failed 但已有 replay 的任务仍展示 Agent 工作区`：验证后置流程失败但有 replay 数据时不退回空白页。
