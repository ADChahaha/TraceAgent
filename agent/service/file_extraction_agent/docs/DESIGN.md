# File Extraction Agent Design

`service.file_extraction_agent` 负责从 `document_processor` 产出的语义 HTML 中抽取结构化字段。它不处理原始 PDF，不保存任务状态，也不做 route policy；这些分别属于 `document_processor`、`backend` 和 `route_policy_agent`。

## 基本实现思路

当前实现是“HTML 索引 + 单 resolution agent + Reading Stages”：

```text
调用方传入 html、task_spec、run_options、model_config
  -> input_adapter 校验 html 非空、task_spec.fields 非空、max_tool_calls > 0
  -> html_index 解析 HTML，基于已有 id 构建 document.tree、elements_by_id、tables_by_id、row_index；tree 按 DOM/section 容器语义保留 section、heading 和同层 block items 的顺序与预览
  -> model_factory 从显式 model_config 或环境变量构造 resolution ChatOpenAI，并注入重试和超时配置
  -> resolution_new 把 task fields 和 document outline 交给 LangGraph tool-calling loop
  -> resolution 可调用 reading stage 工具维护当前右侧执行阶段
  -> html_tools 提供 reading stage / overview / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / set_field / finish
  -> 每个字段通过 set_field 写入 resolved 或 failed，并记录 evidence_ids、rationale 与 actions
  -> finish 校验字段完成度和证据一致性
  -> graph 映射成 ExtractionResult(status, result, failure_reason, trace)
```

`trace` 是前端 replay 和 backend route policy 的共同来源。它包含：

- `reading_stages`：resolution 自维护的当前右侧执行阶段和阶段内 progress，只用于 replay 和工作记忆。
- `document_tree`：从 HTML 推出的混排 outline，包含 section container、heading 和同层 block items 的摘要。
- `field_states`：每个字段的值、状态、证据 id 和失败原因。
- `actions`：resolution 工具调用轨迹，包含读取、查表、写字段、完成等动作。

## 文件结构

```text
service/file_extraction_agent/
├── processor.py
├── input_adapter.py
├── schemas.py
└── impl/
    ├── graph.py
    ├── html_index.py
    ├── html_state.py
    ├── html_tools.py
    ├── model_factory.py
    └── resolution_new.py
```

测试位于：

```text
agent/tests/file_extraction_agent/
```

每个测试文件需要在 `agent/tests/file_extraction_agent/docs/` 下维护一份一一对应的说明文档。

## 公共入口

`processor.extract(...)` 是 Python 入口：

```python
extract(
    *,
    html: str,
    task_spec: TaskSpec | dict,
    model_config: ModelConfig | dict | None = None,
    run_options: RunOptions | dict | None = None,
) -> ExtractionResult
```

HTTP 入口由 `agent/routes/file_extraction_agent.py` 暴露：

```text
POST /v1/file-extraction-agent/extract
```

请求体只需要 `html` 和 `task_spec`，可选 `run_options` 与模型连接配置。核心抽取入口没有 `metadata` 参数；backend 可以在自己的 `agent_stage_runs.request_json` 中保存 metadata，但不会把 metadata 传入 `processor.extract(...)`。

## 输入适配

`input_adapter.py` 负责把外部输入变成内部 `HtmlExtractionInput`：

```text
html + task_spec + run_options
  -> 校验 html 必须是非空字符串
  -> TaskSpec 解析 dict / TaskSpec / 兼容对象
  -> 校验 task_spec.fields 至少一个字段，每个字段必须有 name
  -> RunOptions 解析 dict / RunOptions / 兼容对象
  -> 校验 max_tool_calls 为正数，默认 200
  -> build_html_document(html)
  -> HtmlExtractionInput(html, task_spec, document, run_options)
```

字段类型只允许基础类型和 tagged enum：

```text
string / number / boolean / list[string] / list[number] / null / enum
```

`enum` 是类似 Rust enum 的 tagged union，而不是普通值列表。字段定义通过 `variants` 声明可选分支，每个分支有 `name` 和 payload `type`；payload type 只允许 `string`、`number`、`boolean`、`list[string]`、`list[number]` 或 `null`。模型写入 enum 字段时必须使用：

```json
{"variant": "name", "value": "..."}
```

类型判断以 `variant` 对应的声明为准，不从 `value` 反推类型，避免空列表、数字字符串和布尔值混淆。`null` 类型或 enum 的 `null` variant 可以 resolved 为 `null`，并允许没有 evidence；其他类型仍需要已观察证据。

`FieldDefinition` 兼容旧入参里的 `field_name`，但规范化后统一使用 `name`。

## 模型连接配置

`model_factory.py` 负责把显式 `model_config` 或环境变量归一化成 resolution `ChatOpenAI`：

```text
显式 model_config 或 .env / 进程环境
  -> 读取 BASE_URL / OPENAI_API_KEY / RESOLUTION_MODEL / MODEL
  -> 读取 TEMPERATURE / TOP_P / TOP_K
  -> 读取 MODEL_MAX_RETRIES / MODEL_REQUEST_TIMEOUT
  -> 创建 resolution_model
```

`MODEL_MAX_RETRIES` 未设置时默认是 `6`，用于减少模型服务短暂连接错误导致的整份文档失败。`MODEL_REQUEST_TIMEOUT` 未设置时不显式传入超时，保持底层客户端默认行为。

## HTML 索引

`html_index.py` 只索引已有 HTML id，不生成或修复 id。它会构建：

- `elements_by_id`：元素 id 到规范化元素记录。
- `tree`：给模型看的文档 outline。
- `tables_by_id`：表格 id 到解析后的表格行列。
- `row_index`：表格行 id 到行位置。

索引规则：

- 标题、`p`、`li`、`table`、`tr`、`caption`、`ul`、`ol` 等可追踪元素必须有 id。
- id 必须唯一。
- 表格行作为证据时必须能定位到已有行 id。
- outline 按 DOM/section 容器语义组织：`section` 拥有真实子节点，heading 不会默认吞掉后续平级段落、列表或表格；同层 block 保持同层顺序和预览，不把整张表或完整 DOM 噪声塞给模型。

语义类型从 HTML tag 推断：

| HTML tag | Tree type |
| --- | --- |
| `h1` | `TITLE` |
| `h2`-`h6` | `SECTION_HEADER` |
| `section` | `SECTION` |
| `p` | `TEXT` |
| `ul` / `ol` | `LIST` |
| `table` | `TABLE` |
| `caption` | `CAPTION` |

## Reading Stages

`reading_stages` 不是广义的预生成计划，而是可回放的右侧执行阶段：帮助模型和前端知道“现在围绕什么理解目标读文档”，但不把早期假设变成执行约束。stage 描述文档理解目标，不描述输出字段清单。

`reading_stages` 采用两层结构：

```text
外层 stage
  -> 描述一个大阶段，例如某组字段共享的证据目标、某组表格/条款的理解目标、某个缺失确认目标
  -> 由模型在进入新阶段时 append，不要求一开始列出所有阶段
  -> stage 只有 title/focus/basis/status/finding 等软解释，不硬编码字段绑定

内层 progress
  -> 从该 stage 关联的工具 actions 和 progress events 自动聚合
  -> 展示“看了什么 -> 选了什么依据 -> 得出了什么结论 -> 影响了哪些字段”
```

外层 stage 不应该只是“读第 N 段”或“打开某个 section”。section 是内层 `looked_at` 的事实来源；外层应该表达为什么要看这些内容，以及这个阶段要解决的理解问题。开头不需要单独创建一个“查看 overview”的 stage：resolution prompt 应直接注入 compact overview，`overview()` 工具只作为模型需要刷新或展开结构时的补充。

推荐链路：

```text
resolution 看到 task fields + compact overview
  -> 基于字段语义形成临时 evidence-needs 假设，但不把字段永久绑定到 stage
  -> 准备进入某个理解阶段时，调用 start_stage append 一个新 stage；同一时间只能有一个 in_progress stage
  -> 同一个阶段内先读取、选候选证据、对比或确认缺失
  -> 当前证据足以写一个或多个字段时 append_stage_progress(type="conclude")
  -> 只有进入 conclude 后，才复看 notes 并写字段
  -> 只有发现 conclude 过早且证据不足时，才在同一个 stage 追加 investigate / compare / verify_absence，撤回写字段检查点后补读
  -> 进入下一个大阶段时 complete_stage 当前 stage，再 start_stage 下一个 stage
  -> finish 只校验字段和证据；UI 可把未 completed 的 stage 标为 replay incomplete
```

约束：

- `reading_stages` 是工作记忆和 replay 元数据，不是证据来源，也不是 route policy 结论。
- stage 采用 append-only 事件流：`start_stage` 创建阶段，`append_stage_progress` 追加阶段内进展，`record_stage_evidence` 记录候选证据，`complete_stage` 只写阶段 finding 并收尾；除状态收尾外，不覆盖旧解释。
- `start_stage` 是单活动阶段工具：如果已有 stage 仍是 `in_progress`，必须先 `complete_stage`，不能并行开启另一个 stage。
- progress 是按时间追加的事件流，但阶段工具有读写门控：最新 progress 不是 `conclude` 时处于阅读期，可以继续读证据、记录候选依据或追加 `investigate / compare / verify_absence / conclude`；最新 progress 是 `conclude` 时处于写字段检查点，只能复看本阶段 notes、`set_field`、纠正过早 conclude 的阅读类 progress、`complete_stage` 或 `finish`，不能直接调用读取工具。
- start 时可以在 `basis` 里自然语言说明“某些字段/假设可能共享这块证据，所以准备看什么”，但不要把字段列表写成硬 schema，也不要承诺这个 stage 会解决哪些字段。
- 初始字段/假设分组只是临时 evidence-needs 假设；读到实际文档结构和证据后，可以在后续 `investigate`、`compare` 的 summary 或下一个 stage 的 `basis` 里说明理解目标如何调整。
- stage 不应该为每个字段、标签、问题或假设建立独立项，也不应该复制字段名、标签或假设文本作为 title。
- `set_field` 和 `review_stage_evidence` 必须引用当前 `in_progress` stage，并且只能在该 stage 最新 progress 为 `conclude` 后调用；最终字段仍以已观察到的 inline / row / item 证据为准。
- 进入 `conclude` 后不能直接读取新证据，包括 `overview`、`read_section`、`read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence`、`search_elements`、`scan_document`、`read_element`、`paragraph_extraction` 和底层 `table_extraction`。如果发现证据不足，说明这次 `conclude` 过早；模型应先在同一个 stage 追加新的 `investigate`、`compare` 或 `verify_absence` progress，撤回写字段检查点，让最新 progress 回到证据阶段，再继续读。不能在 conclude 检查点直接读，也不能把这个通道当作普通继续阅读入口。
- UI 可以把外层 stage 展示成右侧阶段，把内层 progress 展示成“看了什么 -> 选了什么依据 -> 得出了什么结论”的展开内容，并折叠工具错误、重复 inline preview、choice/evidence 双字段写入等技术噪声。
- 实验评估应先在排除已知 SEC HTML normalize 问题的 PDF/TXT 子集上对比当前 no-plan baseline；成功标准是 trace 可读性提升且 choice accuracy / evidence F1 不显著回退。

阶段义务：

```text
阅读期
  -> 能调用 overview / read_* / query_table / preview_inline_evidence
  -> 能追加 investigate / compare / verify_absence / conclude
  -> 不能 review_stage_evidence 或 set_field

conclude 检查点
  -> 只在已经读完足够证据、准备写一个或多个字段时追加
  -> 不是泛泛的阶段总结，也不是“稍后还要继续读”的占位

写字段期
  -> latest progress 是 conclude
  -> 能 review_stage_evidence 和 set_field
  -> 不能直接调用读取工具

纠正过早 conclude
  -> 只有 conclude 后发现证据不足时，才在同一个 stage 追加 investigate / compare / verify_absence
  -> 语义是撤回写字段检查点，不是普通继续阅读
  -> 最新 progress 回到阅读期后再继续读取
  -> 读够后再次 append conclude

完成阶段
  -> complete_stage 只在当前理解目标稳定、准备切换到明显不同目标时调用
```

内层 progress event 的 `type` 先收敛为四类；这些不是外层 stage 类型，模型可以在同一个 stage 内多次切换或重复使用：

| type | 语义 | 例子 |
| --- | --- | --- |
| `investigate` | 围绕一个主题理解相关条款，可以覆盖一个或多个 section。 | `Understand what counts as confidential information` |
| `compare` | 当字段判断依赖两处或多处已观察证据之间的关系时使用，例如规则与例外、定义与限制、冲突候选值、表格内容与周边注释。 | `Compare the selected table row with the note that limits when the value applies` |
| `verify_absence` | 在写入缺失类结论前使用，说明已经检查哪些合理相关区域，以及为什么这些区域足以支持“未找到”。 | `Verify that the relevant sections and nearby table notes do not mention the requested item` |
| `conclude` | 汇总已选证据并形成一组相关字段的判断。 | `Conclude post-termination and retention obligations` |

不把 `orient` 作为 progress type：开头看结构来自 prompt 注入的 compact overview，`overview()` 是普通动作。也不使用 `read`、`evidence`、`resolve`、`set_field` 作为 progress type；这些属于原始工具事件、候选证据记录或字段写入。

`compare` 和 `verify_absence` 只在能提高理解透明度时使用：

```text
单条证据已经直接支持字段
  -> investigate
  -> conclude
  -> set_field

字段结论依赖多个已观察证据之间的关系
  -> investigate
  -> compare
  -> conclude
  -> set_field

字段结论表示缺失、空值、无法抽取或其他 absence-like 结果
  -> investigate
  -> verify_absence
  -> conclude
  -> set_field
```

不要把“文档证据和 task field / question 的常规匹配”称为 `compare`；每次 `set_field` 都天然需要这种匹配，它应该写在字段级 `rationale` 里。`compare` 只用于比较两个或多个已经观察到的证据、规则、候选值、表格内容或周边说明之间的关系。

`conclude` 是写字段检查点，不再只是可选总结。模型应先把当前需要看的材料读完，再追加 `conclude` 说明“哪些证据已经足以支持哪些判断或哪些缺失结论”，随后才能 `review_stage_evidence` 和 `set_field`。`complete_stage(finding)` 仍然负责阶段级最终 finding；它不自动追加 `conclude`，避免重复。

如果进入 `conclude` 后发现还缺证据，模型可以先用 `review_stage_evidence(stage_id)` 复看本阶段 notes，确认是不是只是忘了已经记录的依据。若 notes 仍不足以支持字段，不应硬写字段，也不能在 conclude 检查点直接读取；应在同一个 stage 追加新的 `investigate`、`compare` 或 `verify_absence` progress，明确撤回这次过早的写字段检查点，然后继续读取并补充证据，最后再次追加 `conclude`。

阶段内候选证据需要单独记录，不应等到 `set_field` 时才临时回忆：

```text
read_blocks / query_table / read_list
  -> preview_inline_evidence 或观察 row/item 证据
  -> record_stage_evidence(stage_id, evidence_ids, observation, supports?, limits?)
  -> append_stage_progress(stage_id, type="conclude", summary=...)
  -> 后续需要写字段前可 review_stage_evidence(stage_id)
  -> set_field(..., evidence_ids, stage_id, rationale)
```

`record_stage_evidence` 写的是候选依据，不是字段结论：

- `observation`：这组证据直接说明了什么。
- `supports`：它可能支持哪类判断，用自然语言表达，可以提“某些字段/假设可能相关”，但不作为硬绑定。
- `limits`：它不能证明什么、或还需要和哪里对比。
- note 的内部 `note_id` 只用于 trace 排序和展示，模型不需要、也不应该在 `set_field` 里再次引用它。
- 字段和候选 evidence note 的关联由相同 `evidence_ids` 自动推导：只要 `set_field.evidence_ids` 与某个 stage note 的 `evidence_ids` 重叠，UI/replay 就可以把它们连起来。

`review_stage_evidence(stage_id)` 按记录顺序返回该 stage 的 evidence notes，不按重要性排序，也不重排。它只能在当前 stage 进入 `conclude` 后调用；仍然不是 `set_field` 前的必经步骤。`set_field` 必须携带真实 `evidence_ids` 和字段级 `rationale`，不能只引用 note。

## Resolution 阶段

`resolution_new.py` 使用 LangGraph 编排模型和工具：

```text
task_spec + document outline
  -> resolution_model.bind_tools(html_tools.build_tools(state))
  -> agent 选择工具
  -> ToolNode 执行工具并把结果返回给模型
  -> 如果 finish 成功，结束
  -> 如果仍有缺失字段或模型停顿，追加 nudge 继续
  -> 超过 max_tool_calls 或未 finish，返回失败
```

resolution 的目标是让每个字段恰好通过一次 `set_field` 进入最终状态：

- `resolved`：字段值已找到，并且 evidence ids 来自本轮读取、查表或 inline 证据预览结果。
- `failed`：字段无法可靠抽取，需要给出 `failure_reason`。

resolution 直接从字段语义和 compact overview 选择工具，并可用 `reading_stages` 维护 replay 用的当前执行阶段：

```text
Task fields + compact overview
  -> 用字段语义形成可调整的 evidence-needs 假设，不输出固定字段组
  -> 选择下一个大阶段：某组字段共享的证据目标、跨段对比、缺失确认或收尾结论
  -> start_stage(title, focus, basis)
  -> 用 overview / read_section / read_blocks / read_block_range / read_list / query_table 定位和读取证据
  -> 文本证据在写字段前用 preview_inline_evidence 细化到 inline id
  -> 关键候选依据用 record_stage_evidence 记录
  -> append_stage_progress(type="conclude") 进入写字段检查点
  -> 写字段前可用 review_stage_evidence 按顺序复看
  -> 如证据不足，在同一 stage 追加 investigate / compare / verify_absence 后继续读
  -> set_field 写字段级 rationale
  -> 阶段结束时 complete_stage(finding)，再进入下一个 stage
  -> 所有字段完成后 finish
```

resolution system prompt 使用英文表达 replay、表格查询和证据校验等通用约束；精确工具参数和读取行为只写在 `html_tools.py` 的工具函数 docstring 里，并由 LangGraph 绑定工具时注入模型上下文，避免系统 prompt 和工具 schema 漂移。模型可调用工具不暴露 `reason` 参数；字段失败时仍通过 `failure_reason` 记录可审计原因。字段值本身也应跟随任务定义和文档语言输出。

## 工具边界

`html_tools.py` 通过 `build_tools(state)` 暴露模型可调用工具，`state` 只通过闭包绑定，不出现在模型参数里。

工具链路：

```text
start_stage(title, focus, basis)
  -> append 新 reading stage，status=in_progress
  -> 如果已有 in_progress stage，返回错误，要求先 complete_stage
  -> title 是右侧阶段短标题；focus 写准备理解的文档内容；basis 写为什么现在看这里
  -> basis 可以自然语言提到临时字段/假设相关性，但不写硬字段列表

append_stage_progress(stage_id, type, summary)
  -> 在 stage 内 append investigate / compare / verify_absence / conclude 事件
  -> summary 写阶段内发生了什么，不复述工具参数
  -> investigate / compare / verify_absence 属于阅读期；conclude 是写字段检查点
  -> 最新 progress 为 conclude 后，读取工具会拒绝直接读取新证据
  -> 如果 conclude 过早且证据不足，append 阅读类 progress 撤回写字段检查点，读取工具随最新 progress 回到阅读期

record_stage_evidence(stage_id, evidence_ids, observation, supports, limits)
  -> 记录当前 stage 的候选证据 note
  -> evidence_ids 必须来自已观察 inline / row / item 证据
  -> note 不写字段值，也不替代 set_field

review_stage_evidence(stage_id)
  -> 按记录顺序返回 stage 下的候选证据 notes
  -> 不按重要性排序，不自动重排
  -> 只能在当前 stage 的最新 progress 为 conclude 后调用
  -> 可选工具，不是 set_field 前置条件

complete_stage(stage_id, finding)
  -> 把 stage 标为 completed 并写 finding
  -> finding 写这个阶段最终理解到什么，不写字段 checklist
  -> 不自动追加 conclude progress；写字段前必须由模型显式 append conclude

overview()
  -> 返回 section container、heading 和同层 block items 的混排 outline
  -> 只给模型看摘要和读法，不给表格数据行
  -> list item 直接标记为 read_list，并带 block_offset=0
  -> table item 直接标记为 query_table，并带 block_offset=0

read_section(section_id)
  -> 只读取 heading
  -> 只返回该 heading 元素真实后代的 block offsets 和 first-sentence preview
  -> 不把后续平级 p/list/table 隐式算进前一个 heading；这些平级块由 overview 直接暴露
  -> 章节过长时在工具内部触发隔离 scoped reader

read_blocks(section_id, indexes)
  -> 对 section container、heading 真实后代 scope 或 leaf block scope 做 index 列表查询
  -> indexes 来自 overview/read_section 暴露的 block index，由模型挑选需要读取的一个或多个离散块
  -> 返回选中 block 的完整 HTML 或 ref；leaf block scope 使用 indexes=[0]
  -> list 只返回 ref，由 read_list 展开；table 可返回 ref，但也可以直接由 query_table 读取

read_block_range(section_id, start_index, count)
  -> 对和 read_blocks 相同的 scope 做连续窗口读取
  -> start_index 和 count 表示模型要顺序扫的一段上下文，工具最多返回 20 个块
  -> 返回实际读取到的 indexes、blocks 和 evidence_ids；非连续证据仍应使用 read_blocks

read_list(section_id, block_offset, item_offset, number)
  -> 如果 section_id 已经是 overview 给出的 list id，使用 block_offset=0 直接读取
  -> 否则按 section_id + block_offset 找到 list block，再分页返回 list item

query_table(section_id, block_offset, sql)
  -> 如果 section_id 已经是 overview 给出的 table id，使用 block_offset=0 直接查询
  -> 否则按 section_id + block_offset 找到 table block，再执行单条安全 SELECT
  -> 返回 rows、evidence_ids、轻量 table_audit 和查询 summary；不返回逐行空值展开

preview_inline_evidence(source_id, start_index, count)
  -> 只接受本轮已经被读取或扫描观察到的文本类 source_id
  -> 把 source 文本按句号、问号和叹号边界切成 inline 候选；长句不按固定字符数二次截断
  -> 返回 inline_id、source_id、inline_index、文本和字符范围，并把 inline_id 标记为 observed
  -> 只用于写字段前把文本证据细化；表格证据用 query_table 的 row id，列表证据用 read_list 的 item id

set_field(name, value, evidence_ids, status, failure_reason, stage_id, rationale)
  -> 校验字段存在、状态合法、值类型匹配
  -> enum 字段先按 value.variant 查找 variant 定义，再按该 variant 的 payload type 校验 value.value
  -> 校验证据 id 已经被本轮工具观察到
  -> resolved 非 null 字段强制证据粒度：文本必须用 inline id，表格必须包含 row id，列表必须包含 item id
  -> resolved null 字段或 enum null variant 允许 evidence_ids 为空
  -> 校验 stage_id 存在
  -> 写入 state.field_states，包括字段级 rationale

finish()
  -> 校验所有字段都已 set_field
  -> 校验必填字段、证据完整性和最终一致性；null 字段或 enum null variant 不要求 evidence
  -> 返回 ok=true 或错误列表
```

工具调用都会写入 `state.actions`，供 replay、route policy 输入组装和测试断言使用。

## 表格观察

`query_table` 是当前抽取链路里的表格能力。它不做业务硬编码，只根据 HTML 表格结构和模型给出的 SQL 返回事实。

```text
table_id + SQL
  -> 查找 HtmlTable
  -> 校验 SQL 安全性和大表边界
  -> 执行 SQL
  -> 返回 rows：只包含 SQL 选中的列，空 cell 以空字符串直接出现在 values 中
  -> 计算轻量 table_audit：行列数、每列空 cell 数、前 10 个空值行 id、重复表头等结构事实
  -> 计算 summary：本次查询返回行数，以及选中输出列在返回行中的空值数量
  -> 返回 rows + evidence_ids + table_audit + summary
  -> 同步把摘要写入 action trace
```

`table_audit` 和 `summary` 是事实观察，不带 route 结论。`overview` 不返回这些审计内容，只返回 table id、行数和列名，避免大纲膨胀。模型需要判断表格空值背景时必须调用 `query_table`：行级空值直接看 `rows[].values`，整表空值分布看 `table_audit.blank_cells`，本次查询返回行数和输出列空值数量看 `summary`。route policy 后续再结合字段值、证据文本和过程摘要判断是否需要 review。

## 输出映射

`graph.py` 把 `GraphState` 映射成 `ExtractionResult`：

```text
state.field_states 中 status=resolved 的字段
  -> result[field_name] = value

state.reading_stages / document.tree / field_states / actions
  -> trace

resolution 抛异常
  -> status=failed
  -> failure_reason=str(exc)
  -> trace.failed_stage = resolution
```

如果 resolution 调用 `finish` 返回 `ok=false`，整体结果也会是 `failed`，失败原因来自 `finish` 错误列表。

## 设计约束

- 不从文件路径读取原始文件，只消费 `document_processor` 已产出的 HTML。
- 不创建、修复或重写 HTML id。
- 不把 metadata 作为核心抽取输入。
- 不在本模块执行 route policy、人工审核、审计或数据库写入。
- 不把表格工具观察直接解释成 accept/review/reject。
- 任何涉及抽取流程、工具边界、trace 结构或输入契约的变更，都需要同步更新本文档。
