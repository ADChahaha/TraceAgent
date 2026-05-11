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
  -> html_tools 提供 reading stage / overview / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / complete_stage / finish(confirm="finish")
  -> 模型先用 record_stage_evidence(field_name, evidence_ids, ...) 把候选证据逐字段挂账
  -> 每个字段通过 complete_stage(fields=[...]) 批量写入 resolved 或 failed，并校验字段证据已逐字段挂账、粒度足够、类型正确
  -> finish(confirm="finish") 校验字段完成度和证据一致性
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

`reading_stages` 不是广义的预生成计划，而是可回放的右侧执行阶段：帮助模型和前端知道“现在围绕什么理解目标读文档”，但不把早期假设变成执行约束。stage 描述文档理解目标，不描述输出字段清单。一个 stage 是一组相关证据到字段写入的单元：相关字段如果正在从同一处文档内容或同一个对比关系里解决，可以放在同一 stage；不相关字段不要塞进同一 stage。下一批字段如果和当前 stage 的证据或对比关系不相关，就应先完成当前 stage，再开启新 stage。

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
  -> start_stage 后先 append investigate / compare / verify_absence，说明这一阶段开始读什么或确认什么范围
  -> 同一个阶段内再读取、选候选证据、对比或确认缺失
  -> 重要候选依据用 record_stage_evidence(field_name, evidence_ids, ...) 逐字段记录
  -> 当前已有一个或多个字段能可靠写入时 complete_stage(fields=[...])
  -> complete_stage 成功后批量写字段并完成 stage
  -> complete_stage 失败时不写字段，stage 保持 in_progress，继续读或补证据
  -> 进入下一个大阶段时 start_stage 下一个 stage
  -> finish 只校验字段和证据；UI 可把未 completed 的 stage 标为 replay incomplete
```

约束：

- `reading_stages` 是工作记忆和 replay 元数据，不是证据来源，也不是 route policy 结论。
- stage 采用 append-only 事件流：`start_stage` 创建阶段，`append_stage_progress` 追加阶段内进展，`record_stage_evidence` 记录候选证据，`complete_stage` 批量写入本次已经可靠的字段并收尾；除字段写入和状态收尾外，不覆盖旧解释。
- `start_stage` 是单活动阶段工具：如果已有 stage 仍是 `in_progress`，必须先 `complete_stage`，不能并行开启另一个 stage。
- progress 是按时间追加的事件流，但阶段工具有读写门控：`start_stage` 后必须先追加 `investigate / compare / verify_absence` 才能读取；当前 stage 处于阅读期时，可以继续读证据、逐字段记录候选依据、复看本阶段 notes 或追加 `investigate / compare / verify_absence`。当模型认为这次阅读已经足以可靠写下一个或多个字段时，调用 `complete_stage(fields=[...])`；成功后写字段并完成 stage，失败时 stage 不动，继续读取。
- start 时可以在 `basis` 里自然语言说明“某些字段/假设可能共享这块证据，所以准备看什么”，但不要把字段列表写成硬 schema，也不要承诺这个 stage 会解决哪些字段。
- 初始字段/假设分组只是临时 evidence-needs 假设；读到实际文档结构和证据后，可以在后续 `investigate`、`compare` 的 summary 或下一个 stage 的 `basis` 里说明理解目标如何调整。
- 相关字段可以同 stage，不相关字段必须换 stage。判断标准是字段是否由当前 stage 已经读取的文档内容、候选证据或对比关系共同支撑；如果下一批字段需要换到不相关的证据目标，就先完成当前 stage。
- stage 不应该为每个字段、标签、问题或假设建立独立项，也不应该复制字段名、标签或假设文本作为 title。
- `complete_stage.fields` 必须引用当前 `in_progress` stage，字段最终仍以已观察到、且已通过 `record_stage_evidence(field_name=当前字段)` 挂账的 inline / row / item 证据为准。
- `complete_stage.fields` 不能为空，但只表示模型此刻已经能可靠写下来的部分字段，不是 stage 的预设产出列表，也不要求覆盖整个 task。
- `verify_absence` 用来解释缺失类或 `null` 结论检查了哪些范围、为什么足够；它是人类可读的检查点，不是每个字段必须执行的 checklist。
- `complete_stage` 是唯一的阶段出口：如果 `fields` 为空、任何字段带非空 `missing`、字段类型不匹配、证据未被观察、证据粒度不够或失败字段缺少 `failure_reason`，工具返回错误，不写任何字段，也不把 stage 标为 completed。模型应继续在同一个 stage 内读取、查表、预览 inline 或记录候选证据。
- UI 可以把外层 stage 展示成右侧阶段，把内层 progress 展示成“看了什么 -> 选了什么依据 -> 得出了什么结论”的展开内容，并折叠工具错误、重复 inline preview、choice/evidence 双字段写入等技术噪声。
- 实验评估应先在排除已知 SEC HTML normalize 问题的 PDF/TXT 子集上对比当前 no-plan baseline；成功标准是 trace 可读性提升且 choice accuracy / evidence F1 不显著回退。

### 字段级候选证据绑定

`record_stage_evidence` 不是普通备忘录，而是字段写入前的候选证据登记。模型每次认为一组证据可能支撑某个字段时，都要先逐字段挂账：

```text
read_blocks / query_table / read_list
  -> preview_inline_evidence 或观察 row/item 证据
  -> record_stage_evidence(stage_id, field_name, evidence_ids, observation, limits?)
  -> complete_stage(stage_id, fields=[...])
```

校验规则按字段实际值判断，不按业务标签判断：

- `resolved` 且实际值非 `null`：必须有 `evidence_ids`，且这些 id 必须已被同一 stage 的 `record_stage_evidence(field_name=当前字段)` 记录过。
- `resolved` 且实际值为 `null`：允许 `evidence_ids=[]`；如果提供了 evidence，也必须已被同一字段的 `record_stage_evidence` 记录过。
- tagged enum 先按 `variant` 找到声明的 payload type，再按 payload value 判断是否为 `null`；不根据 variant 名称做领域特化。
- `failed`：不要求 evidence，但必须有 `failure_reason`。
- 文本证据仍必须是 `preview_inline_evidence` 返回的 inline id，表格证据必须是 `query_table` 返回的 row id，列表证据必须是 `read_list` 返回的 item id。

这条规则把证据池从“本轮看过的所有 evidence id”收紧为“已经明确挂到当前字段的候选 evidence id”。它不限制模型读取顺序，也不禁止多个字段最终在同一次 `complete_stage` 里提交；但每个字段的证据都必须先单独解释一次，避免模型读完很多内容后把全局证据随手分配给大量字段。

### Stage 软收口

暂不对单个 stage 的读取次数或字段数量做硬限制。为了减少模型一直留在一个宽泛 stage 里工作，先在 prompt 和工具说明里给出软收口规则：

```text
stage started
  -> 读取并细化证据
  -> record_stage_evidence(field_name=...) 产生某字段的候选证据
  -> 优先 complete_stage 写入这些已挂账字段
  -> 只有为了补同一字段或同一证据链的证据时，才继续留在当前 stage 里读取
  -> 下一批字段如果需要不同证据路径，先 complete_stage，再 start_stage
```

这不是业务领域规则，而是通用执行纪律：stage 可以表达一个文档理解目标，但不应该变成“全文读完后一次性填表”的容器。模型仍可在同一 stage 内读多个相关证据；区别是有字段级候选证据后，应先收口提交可靠字段，而不是继续扩展到不相关字段。

阶段义务：

```text
阶段启动
  -> start_stage 后必须先追加 investigate / compare / verify_absence
  -> 不能直接调用读取工具，也不能直接 complete_stage

阅读期
  -> 能调用 overview / read_* / query_table / preview_inline_evidence
  -> 能追加 investigate / compare / verify_absence
  -> 能 review_stage_evidence 复看本 stage 候选依据
  -> 证据足够时用 complete_stage(fields=[...]) 批量写字段并完成 stage

缺失确认
  -> verify_absence 说明缺失类或 null 结论已经检查的范围
  -> 不是每个字段都必须走的硬性步骤

完成阶段
  -> complete_stage 只在至少一个字段已经能可靠落地时调用
  -> fields 只写这次已经可靠的部分字段，不承诺当前 stage 应产出的字段集合
  -> 调用失败时 stage 不动，继续读
```

内层 progress event 的 `type` 先收敛为三类；这些不是外层 stage 类型，模型可以在同一个 stage 内多次切换或重复使用：

| type | 语义 | 例子 |
| --- | --- | --- |
| `investigate` | 围绕一个主题理解相关条款，可以覆盖一个或多个 section。 | `Understand what counts as confidential information` |
| `compare` | 当字段判断依赖两处或多处已观察证据之间的关系时使用，例如规则与例外、定义与限制、冲突候选值、表格内容与周边注释。 | `Compare the selected table row with the note that limits when the value applies` |
| `verify_absence` | 在写入缺失类结论前使用，说明已经检查哪些合理相关区域，以及为什么这些区域足以支持“未找到”。 | `Verify that the relevant sections and nearby table notes do not mention the requested item` |

不把 `orient` 作为 progress type：开头看结构来自 prompt 注入的 compact overview，`overview()` 是普通动作。也不使用 `read`、`evidence`、`resolve`、`set_field` 或 `conclude` 作为 progress type；这些属于原始工具事件、候选证据记录、字段写入或旧写字段检查点。

`compare` 和 `verify_absence` 只在能提高理解透明度时使用：

```text
单条证据已经直接支持字段
  -> investigate
  -> complete_stage(fields=[...])

字段结论依赖多个已观察证据之间的关系
  -> investigate
  -> compare
  -> complete_stage(fields=[...])

字段结论表示缺失、空值、无法抽取或其他 absence-like 结果
  -> investigate
  -> verify_absence
  -> complete_stage(fields=[...])
```

不要把“文档证据和 task field / question 的常规匹配”称为 `compare`；每次字段写入都天然需要这种匹配，它应该写在字段级 `rationale` 里。`compare` 只用于比较两个或多个已经观察到的证据、规则、候选值、表格内容或周边说明之间的关系。

`complete_stage` 是写字段和完成阶段的同一个动作，不再存在单独的 conclude 检查点。模型应先把当前需要看的材料读完，再用 `complete_stage` 提交这次已经可靠的字段。若工具返回错误，说明字段还不能可靠写下；stage 保持 `in_progress`，模型继续读，而不是空关 stage。

阶段内候选证据需要单独记录，不应等到写字段时才临时回忆：

```text
read_blocks / query_table / read_list
  -> preview_inline_evidence 或观察 row/item 证据
  -> record_stage_evidence(stage_id, field_name, evidence_ids, observation, supports?, limits?)
  -> 后续需要写字段前可 review_stage_evidence(stage_id)
  -> complete_stage(stage_id, finding, fields=[...])
```

`record_stage_evidence` 写的是字段级候选依据，不是字段结论：

- `field_name`：这组候选证据准备服务的字段名；一条 note 只挂一个字段，跨段证据可以在同一字段 note 中给多个 `evidence_ids`。
- `observation`：这组证据直接说明了什么。
- `supports`：它可能如何支持该字段，用自然语言表达；这是可读解释，不替代 `complete_stage.fields[].rationale`。
- `limits`：它不能证明什么、或还需要和哪里对比。
- note 的内部 `note_id` 只用于 trace 排序和展示，模型不需要、也不应该在 `complete_stage.fields` 里再次引用它。
- `complete_stage.fields[].evidence_ids` 必须来自同字段的候选 evidence note；UI/replay 也可以按 `field_name + evidence_ids` 把字段写入和候选证据连起来。

`review_stage_evidence(stage_id)` 按记录顺序返回该 stage 的 evidence notes，不按重要性排序，也不重排。它不是 `complete_stage` 前的必经步骤。`complete_stage.fields` 必须携带真实 `evidence_ids` 和字段级 `rationale`，不能只引用 note。

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

resolution 的目标是让每个字段恰好通过一次 `complete_stage.fields[]` 进入最终状态：

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
  -> 关键候选依据用 record_stage_evidence(field_name, ...) 逐字段记录
  -> 写字段前可用 review_stage_evidence 按顺序复看
  -> complete_stage(fields=[...]) 写字段级 rationale 并完成当前 stage
  -> 如证据不足，complete_stage 返回错误，继续在当前 stage 补读
  -> 当前 stage 完成后再进入下一个 stage
  -> 所有字段完成后 finish
```

resolution system prompt 使用英文表达 replay、表格查询和证据校验等通用约束；精确工具参数和读取行为只写在 `html_tools.py` 的工具函数 docstring 里，并由 LangGraph 绑定工具时注入模型上下文，避免系统 prompt 和工具 schema 漂移。模型可调用的读取相关工具必须暴露必填 `reason` 参数，用来解释为什么现在读取、查询或预览这块内容；stage、候选证据、字段写入和 finish 不暴露旧的通用 `reason` 参数。字段失败时仍通过 `failure_reason` 记录可审计原因。字段值本身也应跟随任务定义和文档语言输出。

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
  -> 在 stage 内 append investigate / compare / verify_absence 事件
  -> summary 写阶段内发生了什么，不复述工具参数
  -> investigate / compare / verify_absence 属于阅读期
  -> type="conclude" 会被拒绝；字段写入统一走 complete_stage

record_stage_evidence(stage_id, field_name, evidence_ids, observation, supports, limits)
  -> 记录当前 stage 中某一个字段的候选证据 note
  -> evidence_ids 必须来自已观察 inline / row / item 证据
  -> field_name 必须是 task_spec 中的字段名
  -> note 不写字段值，也不替代 complete_stage.fields

review_stage_evidence(stage_id)
  -> 按记录顺序返回 stage 下的候选证据 notes
  -> 不按重要性排序，不自动重排
  -> 可选工具，不是 complete_stage 前置条件

complete_stage(stage_id, finding, fields)
  -> fields 必须非空，只写本次已经能可靠落地的部分字段
  -> 每个 field 包含 name、value、evidence_ids、rationale、status 和可选 failure_reason
  -> 若任一 field 带非空 missing、类型不匹配、证据未观察或粒度不够，整体返回错误
  -> 失败时不写任何 field_state，不完成 stage，模型继续在当前 stage 读
  -> 成功时批量写 field_states，把 stage 标为 completed，并写 finding

overview(reason)
  -> 返回 section container、heading 和同层 block items 的混排 outline
  -> reason 必填，用来说明为什么现在需要看 outline
  -> section container 返回 `block_count`、`valid_indexes` 和可直接传给 `read_blocks` 的 `read_args`
  -> 如果 heading 的内容实际在父 section 容器里，heading item 返回 `container_id`、`container_block_count`、`valid_indexes` 和容器 `read_args`
  -> 只给模型看摘要和读法，不给表格数据行
  -> list item 直接标记为 read_list，并带 block_offset=0
  -> table item 直接标记为 query_table，并带 block_offset=0

read_section(section_id, reason)
  -> 只读取 heading
  -> reason 必填，用来说明为什么现在读这个 section
  -> 返回 `direct_block_count`，说明该 heading 自身真实后代有多少可读 block
  -> 只返回该 heading 元素真实后代的 block offsets 和 first-sentence preview
  -> 不把后续平级 p/list/table 隐式算进前一个 heading；这些平级块由 overview 直接暴露
  -> 如果 heading 是父 section 容器的首个直接子节点，且正文块在父容器里，返回 `container.block_count`、`container.valid_indexes`、`container.read_args` 和容器内 block previews，模型应改用这些参数调用 `read_blocks`
  -> 章节过长时在工具内部触发隔离 scoped reader

read_blocks(section_id, indexes, reason)
  -> 对 section container、heading 真实后代 scope 或 leaf block scope 做 index 列表查询
  -> reason 必填，用来说明为什么现在读取这些 index
  -> indexes 来自 overview/read_section 暴露的 block index，由模型挑选需要读取的一个或多个离散块
  -> 返回选中 block 的完整 HTML 或 ref；leaf block scope 使用 indexes=[0]
  -> list 只返回 ref，由 read_list 展开；table 可返回 ref，但也可以直接由 query_table 读取

read_block_range(section_id, start_index, count, reason)
  -> 对和 read_blocks 相同的 scope 做连续窗口读取
  -> reason 必填，用来说明为什么现在连续扫上下文
  -> start_index 和 count 表示模型要顺序扫的一段上下文，工具最多返回 20 个块
  -> 返回实际读取到的 indexes、blocks 和 evidence_ids；非连续证据仍应使用 read_blocks

read_list(section_id, block_offset, item_offset, number, reason)
  -> 如果 section_id 已经是 overview 给出的 list id，使用 block_offset=0 直接读取
  -> reason 必填，用来说明为什么现在读取这些 list items
  -> 否则按 section_id + block_offset 找到 list block，再分页返回 list item

query_table(section_id, block_offset, sql, reason)
  -> 如果 section_id 已经是 overview 给出的 table id，使用 block_offset=0 直接查询
  -> reason 必填，用来说明为什么现在查询这张表和这条 SQL 要解决什么证据需求
  -> 否则按 section_id + block_offset 找到 table block，再执行单条安全 SELECT
  -> 返回 rows、evidence_ids、轻量 table_audit 和查询 summary；不返回逐行空值展开

preview_inline_evidence(source_id, start_index, count, reason)
  -> 只接受本轮已经被读取或扫描观察到的文本类 source_id
  -> reason 必填，用来说明为什么现在把这个 source 细化成 inline 证据
  -> 把 source 文本按句号、问号和叹号边界切成 inline 候选；长句不按固定字符数二次截断
  -> 返回 inline_id、source_id、inline_index、文本和字符范围，并把 inline_id 标记为 observed
  -> 只用于写字段前把文本证据细化；表格证据用 query_table 的 row id，列表证据用 read_list 的 item id

complete_stage(stage_id, finding, fields)
  -> 校验 stage_id 是当前 in_progress stage，且 fields 非空
  -> 校验每个字段存在、状态合法、值类型匹配
  -> enum 字段先按 value.variant 查找 variant 定义，再按该 variant 的 payload type 校验 value.value
  -> 校验证据 id 已经被本轮工具观察到
  -> resolved 非 null 字段强制证据粒度：文本必须用 inline id，表格必须包含 row id，列表必须包含 item id
  -> resolved null 字段或 enum null variant 允许 evidence_ids 为空
  -> 任一字段失败则不写任何 field_state，不完成 stage
  -> 全部通过后写入 state.field_states、字段级 rationale 和 stage finding，并把 stage 标为 completed

finish(confirm="finish")
  -> 校验所有字段都已通过 complete_stage 写入
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
