# file_extraction_agent

HTML-based document field extraction agent.

输入是 `document_processor` 产出的语义 HTML。这里先为 HTML 建索引，再用 LangGraph 工具把证据读出来，最后把每个字段写成 `resolved` 或 `failed`，并把全过程放进 `trace`。

## 工作链路

```text
html + task_spec + run_options
  -> input_adapter 校验输入并构造 HtmlExtractionInput
  -> html_index 基于已有 id 构建 document.tree / elements_by_id / tables_by_id / row_index
  -> model_factory 构造 resolution model
  -> resolution_new 注入 compact outline 并挂载工具
  -> start_stage / append_stage_progress / record_stage_evidence 维护人类可读阅读阶段
  -> overview 在 outline 不够时补充混排结构
  -> read_section / read_blocks / read_block_range / read_list / query_table 读取证据
  -> preview_inline_evidence 把已读文本块细化成 inline 证据 id
  -> set_field 写入字段值、字段级 rationale 和失败原因
  -> finish 做最终完整性校验
  -> ExtractionResult.result + trace
```

`document.tree` 不是纯标题树。它按 DOM 里的语义容器组织 outline：`section` 才拥有自己的子节点；和 heading 平级的 `p`、`ul`/`ol`、`table` 会保持同层 item，不会被默认算进前一个 heading。

## Reading Stages

当前是单 resolution agent：模型直接根据字段和 compact outline 读证据、写字段；右侧可读过程由 `reading_stages` 维护。stage 描述“当前围绕什么理解目标读文档”，不是把输出字段、标签、问题或假设逐项列成 checklist。

推荐语义：

```text
compact outline 已在 prompt 中注入
  -> resolution 形成临时 evidence-needs 假设，但不硬绑定字段组
  -> 进入一个大阅读阶段时 start_stage
  -> 读到关键事实、需要对比多处证据、或需要确认缺失时 append_stage_progress
  -> 重要候选依据用 record_stage_evidence 记录；它和字段共用同一批 evidence_ids
  -> 当前证据足以写一个或多个字段时 append_stage_progress(type="conclude")
  -> conclude 之后复看 notes / set_field，并写字段级 rationale
  -> 只有发现 conclude 过早且证据不足时，才在同一个 stage 追加 investigate / compare / verify_absence，撤回写字段检查点后补读
  -> 阶段稳定后 complete_stage；当前 stage 完成前不能 start_stage 开新阶段
  -> finish 只校验字段和证据，不要求计划全部完成
```

`reading_stages` 只用于工作记忆和 replay 展示，不作为证据。stage 是 append-only：旧解释不被覆盖，UI 可以把 progress 展示成“看了什么 -> 选了什么依据 -> 得出了什么结论”，并折叠底层工具错误、重复读取和 finish 校验噪声。

stage 内部采用“先读、再写”的门控：

```text
start_stage
  -> 阅读期：overview / read_* / query_table / preview_inline_evidence / record_stage_evidence
  -> append_stage_progress(type="investigate" | "compare" | "verify_absence") 记录阅读推进
  -> append_stage_progress(type="conclude") 表示进入写字段检查点
  -> 写字段期：review_stage_evidence / set_field
  -> 如果 conclude 过早且证据不足，append_stage_progress(type="investigate" | "compare" | "verify_absence") 撤回写字段检查点
  -> complete_stage
```

只有当前 `in_progress` stage 的最新 progress 是 `conclude` 时，模型才可以调用 `review_stage_evidence` 和 `set_field`。进入 `conclude` 后，本 stage 不能直接读取新证据；如果发现还缺证据，说明这次 `conclude` 过早，应在同一个 stage 追加新的 `investigate`、`compare` 或 `verify_absence` progress，撤回写字段检查点，让最新 progress 回到证据阶段，再继续读取。忘记本阶段已经记录过哪些候选依据时，可以在 conclude 阶段调用 `review_stage_evidence` 复看 notes；如果 notes 不足以支持字段，就不要硬写字段，也不要直接读，应该先撤回 conclude、补证据、再重新 `conclude`。这样 replay 能体现“准备写字段时发现证据不足，于是回到同一问题补查”，同时避免把 `conclude` 用成普通继续阅读入口。

阶段义务：

- 阅读期：用 `overview/read_*/query_table/preview_inline_evidence` 收集证据，可追加 `investigate/compare/verify_absence`，不能 `set_field`。
- conclude 检查点：只有读完并准备写字段时才追加 `conclude`；它不是泛泛的进度总结。
- 写字段期：最新 progress 是 `conclude` 时，可选 `review_stage_evidence`，然后 `set_field(stage_id, rationale, evidence_ids)`；此时不能直接继续读。
- 纠正过早 conclude：只有写前发现证据不足时，才在同一 stage 追加阅读类 progress，撤回写字段检查点；补读后必须重新 `conclude`。
- 完成阶段：只有当前理解目标稳定、准备切换到明显不同目标时才 `complete_stage`。

## 工具

| Tool | 作用 |
| --- | --- |
| `start_stage(title, focus, basis)` | append 一个新的阅读阶段；描述当前要理解什么、为什么现在看这里，不硬绑定字段列表。 |
| `append_stage_progress(stage_id, type, summary)` | 在阶段内追加 `investigate / compare / verify_absence / conclude` 进展事件；`conclude` 是写字段期入口，之后可追加新的阅读类 progress 回到阅读期。 |
| `record_stage_evidence(stage_id, evidence_ids, observation, supports, limits)` | 记录候选证据 note；证据必须是已观察的 inline / table row / list item 粒度。 |
| `review_stage_evidence(stage_id)` | 只能在当前 stage 进入 `conclude` 后调用，按记录顺序复看阶段候选证据。 |
| `complete_stage(stage_id, finding)` | 写阶段级 finding 并把 stage 标为 completed；不会额外追加 `conclude` progress。 |
| `overview()` | 返回混排 outline，包含 `section`、heading、`p`、list、table 的可读摘要。 |
| `read_section(section_id)` | 只读 heading 自身真实后代的 block previews；平级块由 overview 直接暴露。 |
| `read_blocks(section_id, indexes)` | 按模型选择的 index 列表读取离散块；scope 可以是 `section` 容器、heading 真实后代，或单个叶子块 id。 |
| `read_block_range(section_id, start_index, count)` | 从 `start_index` 开始连续读取 `count` 个块，用于顺序补上下文。 |
| `read_list(section_id, block_offset, item_offset, number)` | 对 list block 分页读取 list item；overview 里的顶层 list id 可直接配 `block_offset=0` 使用。 |
| `query_table(section_id, block_offset, sql)` | 对 table block 执行安全 SELECT；overview 里的顶层 table id 可直接配 `block_offset=0` 使用；返回 SQL 行、轻量 `table_audit` 和查询 `summary`。 |
| `preview_inline_evidence(source_id, start_index, count)` | 把已读取的文本块切成 inline 证据候选，返回可用于 `set_field` 的 inline id。 |
| `set_field(name, value, evidence_ids, status, failure_reason, stage_id, rationale)` | 只能在当前 stage 进入 `conclude` 后调用；写字段值或失败状态，并记录字段级 rationale。 |
| `finish()` | 校验所有字段是否已完成。 |

## 字段类型

`task_spec.fields[].type` 支持这些基础类型：

```text
string / number / boolean / list[string] / list[number] / null
```

还支持 tagged enum：

```json
{
  "name": "answer",
  "type": "enum",
  "variants": [
    {"name": "text", "type": "string"},
    {"name": "amounts", "type": "list[number]"},
    {"name": "missing", "type": "null"}
  ]
}
```

enum 字段写入时必须使用 tagged object：

```json
{"variant": "text", "value": "example"}
```

工具按 `variant` 找到声明的 payload type，再校验 `value`，不从 `value` 本身反推类型。`null` 字段或 enum 的 `null` variant 可以 resolved 为 `null`，并允许没有 evidence；其他 resolved 值仍必须有已观察证据。

工具的证据粒度规则：

| 内容类型 | 定位 / 读取工具 | 最终 `set_field` 证据 |
| --- | --- | --- |
| 普通文本、标题、caption | 先用 `read_blocks` / `read_block_range` / scoped scan 读到文本块，再用 `preview_inline_evidence` 预览候选片段。 | 使用 `preview_inline_evidence` 返回的 `inline_id`，例如 `p001_b004::inline-0`。 |
| 列表 | `read_list` 按 `item_offset` 分页读取 list items；顶层 list id 配 `block_offset=0`。 | 至少包含对应 `li` item id；只给 `ul` / `ol` 容器 id 会被拒绝。 |
| 表格 | `query_table` 用安全 SELECT 查询 table rows；顶层 table id 配 `block_offset=0`。 | 至少包含对应 `tr` row id；只给 table id 会被拒绝。 |

`preview_inline_evidence` 不负责替模型选择答案，只把已读文本块拆成可引用的 inline 候选。字段写入时由 `set_field` 强制检查证据是否已经被本轮工具观察到，以及粒度是否足够细。

## 读取规则

`read_section`
  -> 只接受 heading 节点
  -> 只读该 heading 元素真实包含的后代块，不把后面的平级 `p` / list / table 算进去
  -> 如果章节太长，工具内部会触发隔离 scoped reader

`read_blocks`
  -> 接受 section 容器、heading、或叶子块 id
  -> 用 indexes 列表读取模型从 overview/read_section 预览中选中的离散块；非连续证据优先用它
  -> 如果需要连续扫一段上下文，改用 read_block_range，避免把连续窗口塞成很长 indexes 列表
  -> 普通 `p` 直接返回完整文本 HTML
  -> `ul` / `ol` 可以返回 `list-ref`；如果 overview 已给出 list id，也可以直接用 `read_list`
  -> `table` 可以返回 `table-ref`；如果 overview 已给出 table id，也可以直接用 `query_table`

`read_block_range`
  -> 接受和 `read_blocks` 相同的 scope
  -> 用 `start_index + count` 连续读取一段上下文，最多按工具上限返回 20 个块
  -> 返回结构仍包含实际 `indexes`，方便 replay 看清模型读了哪些块

`preview_inline_evidence`
  -> 只接受已经被本轮读取或扫描观察到的文本类元素 id，例如 `p`、heading 或 caption
  -> 把文本按句号、问号和叹号边界切成 inline 候选；长句不按固定字符数二次截断
  -> 返回 `inline_id`、原始 `source_id`、文本和字符范围，并把这些 inline id 标记为已观察
  -> 只在准备写字段证据时使用；table 证据走 `query_table` 的 row id，list 证据走 `read_list` 的 item id

`set_field`
  -> `resolved` 字段必须使用足够细的证据粒度
  -> 文本值使用 `preview_inline_evidence` 返回的 inline id，不能直接用整段 `p` 或 heading id
  -> 表格值必须包含 `query_table` 返回的 `tr` 行 id，不能只用 table id
  -> 列表值必须包含 `read_list` 返回的 `li` item id，不能只用 `ul` / `ol` id

最上层 `p` 可以直接这样读：

```text
overview()
  -> item_id="dp-p-1", type="TEXT", parent_section_id="", read_with="read_blocks"

read_blocks("dp-p-1", [0])
  -> 返回这个 p 的完整内容

preview_inline_evidence("dp-p-1", 0, 20)
  -> 返回 dp-p-1::inline-0 等 inline 证据 id
```

section 下面的 `p` 也一样可以直接按块 id 读取；如果想按父容器顺序读，就先看 overview 里的 section 容器 id，再用 `read_blocks(section_id, [1, 3])` 读取选中的块。和 heading 平级的 `p` 不需要、也不会通过前一个 heading 来读。

连续扫上下文时这样读：

```text
read_block_range("dp-page-1", 4, 6)
  -> 返回 dp-page-1 scope 里 index 4 到 9 的块
```

顶层 list 可以直接这样读：

```text
overview()
  -> item_id="dp-ul-1", type="LIST", read_with="read_list", block_offset=0

read_list("dp-ul-1", 0, 0, 20)
  -> 返回 list items 和 evidence_ids
```

顶层 `table` 可以直接这样查：

```text
overview()
  -> item_id="dp-table-1", type="TABLE", read_with="query_table", block_offset=0

query_table("dp-table-1", 0, "SELECT ... FROM data")
  -> 返回匹配 rows、evidence_ids、轻量 table_audit 和查询 summary
```

表格空值读取规则：

```text
overview()
  -> 只暴露 table id、行数和列名
query_table(...)
  -> rows[].values 只包含 SQL 选中的列；如果选中 cell 为空，值就是 ""
  -> table_audit.blank_cells 按列返回整表空 cell 数和前 10 个空值行 id
  -> summary 返回本次 SQL 的返回行数，以及选中输出列在返回行里有多少空值
```

## 追踪

每次工具调用都会进入 `trace.actions`，字段最终结果会进入 `trace.field_states`。这样 backend 和 frontend 不需要猜模型到底看了什么，只需要回放 action 就行。

## 公共入口

```python
from service.file_extraction_agent.processor import extract

result = extract(
    html='<p id="dp-p-1">正文</p>',
    task_spec={"fields": [{"name": "title", "type": "string", "required": True}]},
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "resolution_model_name": "...",
    },
    run_options={"max_tool_calls": 40},
)
```

更完整的实现边界和设计说明见 [docs/DESIGN.md](docs/DESIGN.md)。
