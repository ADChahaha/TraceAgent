# `task-detail.test.tsx`

这组测试覆盖任务详情页的 replay 工作台主路径，使用注入的加载和提交函数隔离真实 backend。

## 测试链路

```text
任务详情页接收 task_id
  -> loadTaskDetail 先读取 summary
  -> 只继续读取 replay 所需的 result/replay/review，不主动读取 trace/audit
  -> TaskDetail 顶部展示任务 status/stage/route 和失败原因
  -> ReplayReview 展示文档文件名、outline、iframe 文档、plan 和当前 action
  -> result.fields 与 review.fields 合并成 replay 字段卡
  -> set_field action 到达时显示字段值、route badge、route_reason 和证据 chip
  -> 字段证据 chip 只滚动 iframe 文档到对应证据块，不改变当前 replay action
  -> read_element 读取表结构时只高亮并自动读取 caption/表名和表头，不把整张表内容当成已读内容
  -> table_extraction 返回具体行时只高亮返回行，并在自动播放中逐行读取
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
- `字段证据 chip 只定位文档证据，不回跳 replay action`：验证用户从字段写入卡点击证据 chip 时，只暂停并滚动文档 iframe，不把 replay 序号切回最早引用该证据的 action。
- `read_element 查询表结构时高亮表名和表头`：验证模型只看到 `table-ref` 表结构摘要时，ReplayReview 高亮原 HTML 里的 caption/表名和表头，不把整张表或表体内容标成已读。
- `read_element 查询表结构自动播放时读取表名入口`：验证自动播放 `read_element(TABLE)` 时会把首个可读锚点切到 caption/表名入口，不再滚动和读取原始 table/figure block。
- `set_field 的整表证据高亮表名和表头并靠上滚动`：验证字段写入证据是整表 id 时，ReplayReview 高亮 caption/表名和表头，滚动时优先把 caption 靠上放置，不框住整张表。
- `左侧 overview 表格项也滚到表名而不是整表`：验证用户点击左侧表格 overview 时，iframe 滚动目标映射到 caption 优先、表头兜底，而不是原始 table/figure 容器。
- `read_element 查询无 caption 表格时高亮表头而不框整表`：验证表格没有可见 caption 时，ReplayReview 只高亮表头，不生成额外 marker，也不 fallback 框住整张表。
- `table_extraction 只高亮返回行，不高亮整张表或列`：验证 `table_extraction.result.rows` 指定具体返回行时，前端只给这些行加结果高亮，不再高亮整张表或整列。
- `table_extraction 返回具体行时会逐行动画读取`：验证表格查询返回多行时，自动播放会按返回行逐个滚动和读取。
- `set_field 写入证据按 HTML 顺序从上到下读取`：验证字段写入证据即使按乱序 `evidence_ids` 返回，自动播放也会按 iframe 中的真实 HTML 顺序从上到下读取。
- `连续 action 指向同一 block 时不重复播放 outline 鼠标路径`：验证自动播放进入相邻 action 后，如果新的证据仍落在同一个 outline/block 锚点，前端不会再次滚动左侧 outline 和播放鼠标点击路径，但仍会继续滚动 HTML 证据块。
- `自动读取多个证据块时优先滚到当前视口最近的 HTML block`：验证一个 action 返回多个 `evidence_ids` 时，ReplayReview 会按 iframe 当前滚动位置选择距离视口中心最近的证据块先读，避免每次都从返回列表第一个块开始。
- `必填字段没有 agent value 时在 replay 末尾显示空复核输入`：验证 agent 没有写入必填字段但 route_policy 要求 review 时，replay 仍会显示“等待人工补录”的字段卡和空输入框，提交时把人工补录值发给 review 接口。
- `reject 字段只显示拒绝路由，不提供人工修改入口`：验证 route 为 `reject` 的字段不出现复核 textarea 和提交按钮，避免用户在前端绕过拒绝结论。
- `failed 任务会展示 backend 返回的失败原因`：验证 summary 中的 `error_message` 会在 failed 详情页顶部以“任务失败”提示展示。
- `failed 但已有 result/trace 的任务仍展示 replay`：验证 route_policy 或后置流程失败时，只要 backend 已经能返回 replay，详情页仍展示 replay，不退回到空白或旧 trace 面板。
