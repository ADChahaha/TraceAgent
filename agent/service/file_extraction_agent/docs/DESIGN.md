# File Extraction Agent Design

`service.file_extraction_agent` 负责从 `document_processor` 产出的语义 HTML 中抽取结构化字段。它不处理原始 PDF，不保存任务状态，也不做 route policy；这些分别属于 `document_processor`、`backend` 和 `route_policy_agent`。

## 基本实现思路

当前实现是“HTML 索引 + 空 broad 占位 + resolution 直接工具执行 + 轻量 update_plan 记忆”：

```text
调用方传入 html、task_spec、run_options、model_config
  -> input_adapter 校验 html 非空、task_spec.fields 非空、max_tool_calls > 0
  -> html_index 解析 HTML，基于已有 id 构建 document.tree、elements_by_id、tables_by_id、row_index；tree 按 DOM/section 容器语义保留 section、heading 和同层 block items 的顺序与预览
  -> model_factory 从显式 model_config 或环境变量构造 broad / resolution 两个 ChatOpenAI，并注入重试和超时配置
  -> broad_new 不调用模型，直接写入空 BroadPlan 作为 trace 兼容占位
  -> graph 把 broad_model 挂到 state.document_scan_model，作为可选隔离全文扫描模型
  -> resolution_new 把 task fields 和 document outline 交给 LangGraph tool-calling loop
  -> html_tools 提供 update_plan / overview / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / set_field / finish
  -> 模型用 update_plan 声明当前局部工作单元和相关字段，读取对应证据后直接 set_field 写入 resolved 或 failed
  -> finish 校验字段完成度和证据一致性
  -> graph 映射成 ExtractionResult(status, result, failure_reason, trace)
```

`trace` 是前端 replay 和 backend route policy 的共同来源。它包含：

- `broad_plan`：no-plan 实验中的兼容占位，默认是 `summary="No broad plan"`、空 `plan` 和空 `risks`。
- `plan_statuses`：resolution 的轻量计划进度和当前工作单元状态。
- `document_tree`：从 HTML 推出的混排 outline，包含 section container、heading 和同层 block items 的摘要。
- `field_states`：每个字段的值、状态、证据 id、原因或失败原因。
- `actions`：resolution 工具调用轨迹，包含读取、查表、写字段、完成等动作。

## 文件结构

```text
service/file_extraction_agent/
├── processor.py
├── input_adapter.py
├── schemas.py
└── impl/
    ├── broad_new.py
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

字段类型只允许：

```text
string / number / boolean / list[string] / list[number]
```

`FieldDefinition` 兼容旧入参里的 `field_name`，但规范化后统一使用 `name`。

## 模型连接配置

`model_factory.py` 负责把显式 `model_config` 或环境变量归一化成 broad / resolution 两个 `ChatOpenAI`：

```text
显式 model_config 或 .env / 进程环境
  -> 读取 BASE_URL / OPENAI_API_KEY / BROAD_MODEL / RESOLUTION_MODEL / MODEL
  -> 读取 TEMPERATURE / TOP_P / TOP_K
  -> 读取 MODEL_MAX_RETRIES / MODEL_REQUEST_TIMEOUT
  -> 分别创建 broad_model 和 resolution_model
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

## Broad 阶段

`broad_new.py` 在当前实现中不再调用模型，也不再生成路线计划。它只写入空 `BroadPlan`，让下游 trace 结构保持兼容。

```text
GraphState
  -> run_broad_planner(...)
  -> state.broad_plan = BroadPlan(summary="No broad plan", plan=[], risks=[])
```

约束：

- broad 不调用模型，不读取完整 HTML 来制定路线。
- broad 不写最终字段值，也不写候选章节、元素、关键词或风险。
- broad_model 只会在 resolution 主 agent 显式调用 `scan_document`，或 `read_section` 因章节过长自动触发 scoped scan 时，作为隔离 reader 被调用；它不会获得工具，也不能递归调用其他 agent。
- `build_broad_messages`、`return_broad_plan` 和解析函数暂时保留，方便和旧 plan 模式对比或回滚。

## 轻量 Plan 记忆

`update_plan` 不是 stage 状态机，也不是字段证据账本。它只是轻量工作记忆和 replay 标题，用来让模型和用户看清“这一段准备解决哪些相关字段、为什么读这些条款、最后写了哪些字段”。最终字段仍由 `set_field` 写入；`update_plan` 不参与 scorer，不替代字段 rationale，也不做 plan 级硬校验。

推荐 prompt 纪律：

- 每次 `update_plan` 都应描述一个局部工作单元，而不是整份文档或全部字段。
- `update_plan` 应写出本段可能相关的字段或字段组，让后续读取和写入有明确范围。
- 本段内的读取、预览和 `set_field` 应尽量围绕 `update_plan` 中声明的相关字段展开。
- 如果模型发现另一个字段和当前证据路径确实相关，可以顺手处理；但不应让一个 plan 漫延成全字段填表。
- 当要切换到不同主题、不同条款区域或明显不同的字段组时，应先开启新的 `update_plan`。
- 为了增强模型记忆并改善前端 replay，可鼓励 `set_field.evidence_ids` 优先使用当前 `update_plan` 之后读到或重新 preview 过的证据。
- 如果某个字段需要复用更早 plan 里读过的相关证据，prompt 应鼓励模型在当前 plan 内重新读取或重新 `preview_inline_evidence`，而不是只凭长上下文记忆直接写字段。
- 这些规则只放在 prompt 中作为软约束，不在 `set_field`、`finish` 或 scorer 中加入 plan 级硬校验。

```text
update_plan 声明当前局部工作单元
  -> read_section / read_blocks / read_block_range / read_list / query_table 读取相关证据
  -> preview_inline_evidence 细化文本证据
  -> set_field 直接写字段值和 evidence_ids
  -> 换到明显不同的主题或字段组前，再调用 update_plan
```

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

resolution 会在必要时调用 `update_plan` 来记录当前局部工作单元，但它仍然直接从字段语义和文档 outline 选择工具：

```text
Task fields + document outline
  -> 选择下一个未完成字段或相关字段组
  -> 用 update_plan 声明当前局部工作单元和可能相关字段
  -> 用 overview / read_section / read_blocks / read_block_range / read_list / query_table 定位和读取证据
  -> 文本证据在写字段前用 preview_inline_evidence 细化到 inline id
  -> 证据足够就立即 set_field
  -> 所有字段完成后 finish
```

resolution system prompt 使用英文表达 replay、表格查询、plan 软记忆和证据校验等通用约束；精确工具参数和读取行为只写在 `html_tools.py` 的工具函数 docstring 里，并由 LangGraph 绑定工具时注入模型上下文，避免系统 prompt 和工具 schema 漂移。除 `update_plan`、`set_field` 和 `finish` 外，每个工具调用都需要 `reason`，并要求 reason 尽量使用文档语言；字段值本身也应跟随任务定义和文档语言输出。

## 工具边界

`html_tools.py` 通过 `build_tools(state)` 暴露模型可调用工具，`state` 只通过闭包绑定，不出现在模型参数里。

工具链路：

```text
update_plan(plan_index, status, reason)
  -> 记录当前局部工作单元、相关字段和 replay 标题
  -> 只更新 plan_statuses，不写字段、不绑定证据、不参与最终校验

overview()
  -> 返回 section container、heading 和同层 block items 的混排 outline
  -> 只给模型看摘要和读法，不给表格数据行
  -> list item 直接标记为 read_list，并带 block_offset=0
  -> table item 直接标记为 query_table，并带 block_offset=0

read_section(section_id, reason)
  -> 只读取 heading
  -> 只返回该 heading 元素真实后代的 block offsets 和 first-sentence preview
  -> 不把后续平级 p/list/table 隐式算进前一个 heading；这些平级块由 overview 直接暴露
  -> 章节过长时在工具内部触发隔离 scoped reader

read_blocks(section_id, indexes, reason)
  -> 对 section container、heading 真实后代 scope 或 leaf block scope 做 index 列表查询
  -> indexes 来自 overview/read_section 暴露的 block index，由模型挑选需要读取的一个或多个离散块
  -> 返回选中 block 的完整 HTML 或 ref；leaf block scope 使用 indexes=[0]
  -> list 只返回 ref，由 read_list 展开；table 可返回 ref，但也可以直接由 query_table 读取

read_block_range(section_id, start_index, count, reason)
  -> 对和 read_blocks 相同的 scope 做连续窗口读取
  -> start_index 和 count 表示模型要顺序扫的一段上下文，工具最多返回 20 个块
  -> 返回实际读取到的 indexes、blocks 和 evidence_ids；非连续证据仍应使用 read_blocks

read_list(section_id, block_offset, item_offset, number, reason)
  -> 如果 section_id 已经是 overview 给出的 list id，使用 block_offset=0 直接读取
  -> 否则按 section_id + block_offset 找到 list block，再分页返回 list item

query_table(section_id, block_offset, sql, reason)
  -> 如果 section_id 已经是 overview 给出的 table id，使用 block_offset=0 直接查询
  -> 否则按 section_id + block_offset 找到 table block，再执行单条安全 SELECT
  -> 返回 rows、evidence_ids、轻量 table_audit 和查询 summary；不返回逐行空值展开

preview_inline_evidence(source_id, start_index, count, reason)
  -> 只接受本轮已经被读取或扫描观察到的文本类 source_id
  -> 把 source 文本按句子边界切成 inline 候选；长合同句保持完整，不按固定字符数二次截断
  -> 返回 inline_id、source_id、inline_index、文本和字符范围，并把 inline_id 标记为 observed
  -> 只用于写字段前把文本证据细化；表格证据用 query_table 的 row id，列表证据用 read_list 的 item id

set_field(name, value, evidence_ids, reason, status, failure_reason)
  -> 校验字段存在、状态合法、值类型匹配
  -> 校验证据 id 已经被本轮工具观察到
  -> resolved 字段强制证据粒度：文本必须用 inline id，表格必须包含 row id，列表必须包含 item id
  -> 写入 state.field_states

finish()
  -> 校验所有字段都已 set_field
  -> 校验必填字段、证据完整性和最终一致性
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

`table_audit` 和 `summary` 是事实观察，不带 route 结论。`overview` 不返回这些审计内容，只返回 table id、行数和列名，避免大纲膨胀。模型需要判断表格空值背景时必须调用 `query_table`：行级空值直接看 `rows[].values`，整表空值分布看 `table_audit.blank_cells`，本次查询返回行数和输出列空值数量看 `summary`。resolution 必须在 `set_field.reason` 里解释这些观察对当前字段是否有影响；route policy 后续再结合字段值、证据文本和过程摘要判断是否需要 review。

## 输出映射

`graph.py` 把 `GraphState` 映射成 `ExtractionResult`：

```text
state.field_states 中 status=resolved 的字段
  -> result[field_name] = value

state.broad_plan / plan_statuses / document.tree / field_states / actions
  -> trace

broad 或 resolution 抛异常
  -> status=failed
  -> failure_reason=str(exc)
  -> trace.failed_stage = broad 或 resolution
```

如果 resolution 调用 `finish` 返回 `ok=false`，整体结果也会是 `failed`，失败原因来自 `finish` 错误列表。

## 设计约束

- 不从文件路径读取原始文件，只消费 `document_processor` 已产出的 HTML。
- 不创建、修复或重写 HTML id。
- 不把 metadata 作为核心抽取输入。
- 不在本模块执行 route policy、人工审核、审计或数据库写入。
- 不把表格工具观察直接解释成 accept/review/reject。
- 任何涉及抽取流程、工具边界、trace 结构或输入契约的变更，都需要同步更新本文档。
