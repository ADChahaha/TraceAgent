# `task-detail.test.tsx`

这组测试覆盖任务详情页的 replay 工作台主路径，使用注入的加载和提交函数隔离真实 backend。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 先读取 summary
  -> 只继续读取 replay 所需的 result/replay/review，不主动读取 trace/audit
  -> TaskDetail 顶部展示任务 status/stage/route 和失败原因
  -> ReplayReview 展示文档文件名、左侧文档结构/虚拟文件树、中间铺满容器的 iframe 文档和右侧从上到下的 reason/tool 文字流
  -> iframe 内部把 backend display_html 包成通用专业文档画布，用浅工作区承托白色纸面，并统一标题、段落、列表和 booktabs 风格表格排版，不引入具体行业语义
  -> iframe 包装 display_html 时删除页码、页眉、页脚版本号等文档 chrome，避免 `Page 2` 和 `428249v2` 继续显示在中间画布
  -> result.fields 与 review.fields 合并成 replay 字段卡
  -> 真实 file_extraction_agent 工具 tree/read/query_table/bind_evidence/review_field/write_field/submit_result 以 Codex 风格灰色运行记录行展示，reason 是普通正文，read 系列工具使用搜索图标，anchors 只服务左侧树和 HTML 动画、不进入右侧文字流
  -> 右侧 reason 只读取 action.reason；没有真实 reason 时只显示 tool 行，不灌默认占位文案
  -> file_extraction_agent 的 path action 会在左侧虚拟文件树高亮当前文件和父级目录
  -> 虚拟文件树按工具返回顺序展示，不把文件夹提升到文件前面；leaf 在 UI 上按 outline 标题显示，不展示 `.md/.table/.list` 扩展名
  -> 左侧文件树顶部不展示大标题、说明或展开/折叠双按钮，只保留一个关闭左栏的小按钮；侧栏使用较窄的 Codex 式默认宽度，左右两侧栏都可通过竖向分隔条拖拽调整，关闭左栏后文档区扩展，并在左上角显示重新打开按钮；单个目录仍通过点击节点展开或收起
  -> 左栏关闭时自动播放不再执行左侧树形导航和鼠标路径动画，文档结构也不显示 `page_001` / `page_002` 分页容器、`Page 2` 页码和 `428249v2` 这类页脚版本号
  -> path + selector 证据先映射成 iframe 中的真实 HTML id，再用于文档高亮和自动阅读
  -> 右侧文字流默认不展示额外操作，hover 到某条 action 才显示跳到该步和只播放该步的小按钮；点击文字本身继续下一步
  -> search_elements action 只在右侧显示检索词和命中数，命中片段留给 HTML 高亮/自动阅读
  -> action result 返回 query_audit.summary、table_audit.summary 或其他 *_audit.summary 时，不进入右侧文字流；table_extraction 失败或 0 行只显示工具行摘要
  -> set_field action 到达时显示字段值、route badge、route_reason 和证据 chip
  -> 长字段值在字段写入卡内部独立滚动，复核输入和提交按钮不被长列表挤出卡片底部
  -> 字段证据 chip 只滚动 iframe 文档到对应证据块，不改变当前 replay action
  -> read_element 读取表结构时只高亮并自动读取 caption/表名和表头，不把整张表内容当成已读内容
  -> table_extraction 返回具体行时只高亮返回行，并在自动播放中逐行读取
  -> table_extraction 失败或返回 0 行时不使用 table_id、SQL 或动作 reason 兜底高亮或读取文档
  -> 连续 action 指向同一 HTML block 时跳过重复 outline 鼠标路径，只继续处理文档证据
  -> 一个 action 有多个证据块时，按 iframe 当前视口距离优先读取最近的 HTML block
  -> set_field 写入证据按 HTML 文档顺序从上到下读取，不按 evidence_ids 数组顺序乱跳
  -> route=review 的字段显示复核输入，默认值来自 agent_value
  -> agent 没有返回必填字段时，replay 末尾显示空复核输入，供人工补录
  -> route=reject 的字段只显示拒绝路由，不允许在前端修改
  -> 用户提交 revise_and_approve 后刷新详情
  -> 用刷新后的 summary 回写最近任务 localStorage 状态
```

## 测试函数

- `loadTaskDetail 只拉 replay 所需数据，不再加载 trace 和 audit`：验证详情聚合函数只请求 summary、result、replay 和 waiting_review 时的 review handoff，并把 `trace/audit` 留成 `null`，避免已移除的下方展示 UI 继续拉取无用数据。
- `低层 API 仍保留 trace 和 audit 读取能力`：验证 `getTaskTrace` 和 `getTaskAudit` 这些底层 API 函数仍可单独使用，详情页收口不等于删除 backend 调试接口适配。
- `waiting_review 任务只展示 replay，并在 review 字段卡片里提交修正`：验证详情页不再出现“结果/复核/证据/审计”tab，也不展示原始 trace/audit 文案；当前 `set_field` 卡片显示字段显示名、`review` badge 和 route 原因，并能提交 `revise_and_approve` payload，刷新后同步最近任务缓存。
- `enum 字段复核提交 tagged payload 而不是字符串`：验证复核区遇到 `enum` tagged payload 时会显示结构化编辑器，用户可以切换枚举 variant；提交时 `review_value` 仍保持 `{variant, value}` 结构，而不是被前端压成普通字符串。
- `真实 file_extraction_agent 工具以 Codex 工具行展示`：验证 `tree/read/query_table/bind_evidence/review_field/write_field/submit_result` 使用真实 flat action contract；右侧 reason 是普通正文，tool 行是灰色运行记录式的一行摘要，`read` 使用搜索图标标记并显示 `Read paragraph Confidential` 这类语义文案，anchors 不进入右侧文字流，read/query/submit 的返回正文、Rxxx 和校验错误不进入右侧文字流。
- `read 工具摘要按 paragraph/table/list 语义展示，不暴露虚拟文件扩展名`：验证 `read` 对 `.md/.table/.list` 虚拟路径分别显示为 `Read paragraph/table/list 名称`，并去掉编号前缀和文件扩展名，避免右侧工具行出现 `Read 001-xxx.md` 这类文件名式文案。
- `中间 HTML 直接铺满文档容器，不保留灰色边框槽位`：验证文档 iframe 外层不再带圆角卡片边框和灰色 gutter，iframe 自身以无边框 block 方式铺满中间容器。
- `中间 HTML 使用通用专业文档画布排版`：验证 iframe `srcDoc` 会注入 `document-canvas`、浅工作区、白色纸面、清晰纸面边界、顶部纸边、可见投影、serif 正文、列表间距和 booktabs 风格表格样式，让任意文档类型都以有层级的专业审阅画布呈现。
- `中间 HTML 画布不展示页码和页脚噪声`：验证 replay 包装旧 `display_html` 时会移除 `.page-number`、`data-type=page_footer` 和 `block-page_footer` 节点，保留正文标题和正文段落。
- `右侧 agent 没有真实 reason 时只显示 tool 行，不灌默认占位文案`：验证没有 `action.reason` 的真实工具调用不会显示“模型等待下一步动作”或“等待模型执行下一步”等伪 reason。
- `file_extraction_agent 的虚拟文件树固定在左侧并随 path action 高亮`：验证真实工具返回的虚拟 path 会被组织成左侧文件树；顶部旧标题/说明/双按钮不再展示，只保留小号关闭左栏按钮；关闭后整列从布局中消失，文档区左上角提供重新打开按钮；目录节点仍可点开收起，切到 `read` action 时当前文件以 outline 标题展示并加 active 状态，父级目录加 active-path 状态，UI 不暴露 `.md` 扩展名。
- `左右侧栏可以通过分隔条手动调整宽度`：验证 replay 桌面三栏布局提供左侧栏和右侧栏的竖向 `separator`；拖拽左侧分隔条会更新左栏宽度，拖拽或键盘方向键操作右侧分隔条会更新 agent 栏宽度；关闭左侧栏后左侧分隔条消失，右侧分隔条仍保留。
- `虚拟文件树按工具返回顺序展示，不把文件夹排到文件上面`：验证左侧虚拟文件树保留 `tree` 工具文本里的原始顺序，不做 folder-first 或字母排序；文件 leaf 显示为去掉编号和扩展名后的 outline 标题。
- `path + selector 证据会映射并高亮 iframe HTML`：验证 `bind_evidence` 里的 `{path, sentences}` 和 `evidence_texts` 会先在 iframe 中匹配真实证据文本并生成 inline evidence span；当前高亮只落在该 inline 文本上，不把整段 HTML block 加成当前高亮，同时左侧文件树仍定位到证据文件。
- `左侧栏关闭后自动播放不再执行左侧鼠标路径动画`：验证关闭文档结构/文件树后，自动播放不会再滚动左侧树或显示左侧路径 cursor，避免左栏已关闭时仍出现无意义的鼠标动画。
- `文档结构不显示 page_001、页码和页脚这类节点`：验证 backend outline 或 HTML 中的分页容器、页码和页脚版本号不会作为 `Page 1/Page 2/Header: Page 2/428249v2` 节点出现在左侧，只保留实际标题节点。
- `右侧 agent 条目悬浮时显示跳转和单步播放按钮，左键文字继续下一步`：验证默认文字流里不显示小按钮；hover 某条 action 后显示“跳到第 N 步”和“只播放第 N 步”，点击文字仍只推进 replay 到下一步。
- `动作 result 的诊断内容不进入右侧文字流，字段写入卡也不承接诊断文字`：验证 `*_audit.summary` 只作为工具 result 数据存在，不在右侧 agent 流里展开；后续 `set_field` 字段卡也只展示字段值、路由和证据。
- `search_elements 动作只在右侧显示工具行摘要，命中片段留给 HTML 高亮`：验证当前 action 是 `search_elements` 时，右侧只显示检索摘要和 match count，不把候选证据 snippet 作为右侧内容重复展示。
- `字段证据 chip 只定位文档证据，不回跳 replay action`：验证用户从字段写入卡点击证据 chip 时，只暂停并滚动文档 iframe，不把 replay 序号切回最早引用该证据的 action。
- `read_element 查询表结构时高亮表名和表头`：验证模型只看到 `table-ref` 表结构摘要时，ReplayReview 高亮原 HTML 里的 caption/表名和表头，不把整张表或表体内容标成已读。
- `read_element 查询表结构自动播放时读取表名入口`：验证自动播放 `read_element(TABLE)` 时会把首个可读锚点切到 caption/表名入口，不再滚动和读取原始 table/figure block。
- `set_field 的整表证据高亮表名和表头并靠上滚动`：验证字段写入证据是整表 id 时，ReplayReview 高亮 caption/表名和表头，滚动时优先把 caption 靠上放置，不框住整张表。
- `左侧 overview 表格项也滚到表名而不是整表`：验证用户点击左侧表格 overview 时，iframe 滚动目标映射到 caption 优先、表头兜底，而不是原始 table/figure 容器。
- `read_element 查询无 caption 表格时高亮表头而不框整表`：验证表格没有可见 caption 时，ReplayReview 只高亮表头，不生成额外 marker，也不 fallback 框住整张表。
- `table_extraction 只高亮返回行，不高亮整张表或列`：验证 `table_extraction.result.rows` 指定具体返回行时，前端只给这些行加结果高亮，不再高亮整张表或整列。
- `table_extraction 失败或空结果时不自动读取整表`：验证 SQL 工具失败时显示“查询失败”警示，条件查询返回 0 行时显示“未查到结果”普通提示；两种情况都不把 `table_id`、SQL 或动作 reason 当作回放锚点，避免前端表现成模型读取了结果之外的文档内容。
- `table_extraction 返回具体行时会逐行动画读取`：验证表格查询返回多行时，自动播放会按返回行逐个滚动和读取。
- `set_field 写入证据按 HTML 顺序从上到下读取`：验证字段写入证据即使按乱序 `evidence_ids` 返回，自动播放也会按 iframe 中的真实 HTML 顺序从上到下读取。
- `连续 action 指向同一 block 时不重复播放 outline 鼠标路径`：验证自动播放进入相邻 action 后，如果新的证据仍落在同一个 outline/block 锚点，前端不会再次滚动左侧 outline 和播放鼠标点击路径，但仍会继续滚动 HTML 证据块。
- `自动读取多个证据块时优先滚到当前视口最近的 HTML block`：验证一个 action 返回多个 `evidence_ids` 时，ReplayReview 会按 iframe 当前滚动位置选择距离视口中心最近的证据块先读，避免每次都从返回列表第一个块开始。
- `必填字段没有 agent value 时在 replay 末尾显示空复核输入`：验证 agent 没有写入必填字段但 route_policy 要求 review 时，replay 仍会显示“等待人工补录”的字段卡和空输入框，提交时把人工补录值发给 review 接口。
- `长字段写入卡把字段内容和复核区分离，避免全屏时复核入口被撑出视口`：验证长列表字段写入时，字段值位于独立内容区，复核 textarea 和提交按钮仍在字段卡的复核区中，不会混进长内容滚动区域；同时确认 replay 根节点带有字段写入布局状态，供全屏样式为底部复核区预留高度。
- `reject 字段只显示拒绝路由，不提供人工修改入口`：验证 route 为 `reject` 的字段不出现复核 textarea 和提交按钮，避免用户在前端绕过拒绝结论。
- `failed 任务会展示 backend 返回的失败原因`：验证 summary 中的 `error_message` 会在 failed 详情页顶部以“任务失败”提示展示。
- `failed 但已有 result/trace 的任务仍展示 replay`：验证 route_policy 或后置流程失败时，只要 backend 已经能返回 replay，详情页仍展示 replay，不退回到空白或旧 trace 面板。
