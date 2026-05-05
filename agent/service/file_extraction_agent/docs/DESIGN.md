# File Extraction Agent Design

`service.file_extraction_agent` 负责从 `document_processor` 产出的语义 HTML 中抽取结构化字段。它不处理原始 PDF，不保存任务状态，也不做 route policy；这些分别属于 `document_processor`、`backend` 和 `route_policy_agent`。

## 基本实现思路

当前实现是“HTML 索引 + broad 规划 + resolution 工具执行”：

```text
调用方传入 html、task_spec、run_options、model_config
  -> input_adapter 校验 html 非空、task_spec.fields 非空、max_tool_calls > 0
  -> html_index 解析 HTML，基于已有 id 构建 document.tree、elements_by_id、tables_by_id、row_index
  -> model_factory 从显式 model_config 或环境变量构造 broad / resolution 两个 ChatOpenAI
  -> broad_new 读取 task_spec、document.tree 和完整 HTML，只用 return_broad_plan 产出摘要、计划和风险
  -> resolution_new 把 broad plan 和 document outline 交给 LangGraph tool-calling loop
  -> html_tools 提供 update_plan / read_element / read_section / table_extraction / paragraph_extraction / set_field / finish
  -> 每个字段通过 set_field 写入 resolved 或 failed，并记录 evidence_ids 与 actions
  -> finish 校验字段完成度和证据一致性
  -> graph 映射成 ExtractionResult(status, result, failure_reason, trace)
```

`trace` 是前端 replay 和 backend route policy 的共同来源。它包含：

- `broad_plan`：broad 阶段返回的摘要、计划和风险。
- `plan_statuses`：resolution 执行计划时的 in_progress / completed 状态。
- `document_tree`：从 HTML 推出的目录和表格概览。
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
- outline 只保留标题层级和表格概览，不把整张表或完整 DOM 噪声塞给模型。

语义类型从 HTML tag 推断：

| HTML tag | Tree type |
| --- | --- |
| `h1` | `TITLE` |
| `h2`-`h6` | `SECTION_HEADER` |
| `p` | `TEXT` |
| `li` | `LIST_ITEM` |
| `table` | `TABLE` |
| `caption` | `CAPTION` |

## Broad 阶段

`broad_new.py` 是规划器，不是抽取器。它读取 task spec、document tree 和完整 HTML，只允许通过 `return_broad_plan(summary, plan, risks)` 返回结构化计划。

```text
GraphState
  -> build_broad_messages(...)
  -> broad_model.bind_tools([return_broad_plan], tool_choice="return_broad_plan")
  -> parse_broad_plan_tool_call(...)
  -> state.broad_plan = BroadPlan(summary, plan, risks)
```

约束：

- broad 不能调用文档读取工具。
- broad 不能写最终字段值。
- plan 要写清楚 resolution 后续应读哪个章节、哪个元素或哪张表，以及应该使用什么工具。
- 表格计划应先读取表格结构，再规划 SQL 查询。
- 表格质量问题只写成后续需要检查的事实，不在 broad 阶段提前下风险结论。

## Resolution 阶段

`resolution_new.py` 使用 LangGraph 编排模型和工具：

```text
broad_plan + task_spec + document outline
  -> resolution_model.bind_tools(html_tools.build_tools(state))
  -> agent 选择工具
  -> ToolNode 执行工具并把结果返回给模型
  -> 如果 finish 成功，结束
  -> 如果仍有缺失字段或模型停顿，追加 nudge 继续
  -> 超过 max_tool_calls 或未 finish，返回失败
```

resolution 的目标是让每个字段恰好通过一次 `set_field` 进入最终状态：

- `resolved`：字段值已找到，并且 evidence ids 来自本轮读取或查表结果。
- `failed`：字段无法可靠抽取，需要给出 `failure_reason`。

## 工具边界

`html_tools.py` 通过 `build_tools(state)` 暴露模型可调用工具，`state` 只通过闭包绑定，不出现在模型参数里。

工具链路：

```text
update_plan(plan_index, status, reason)
  -> 只能按 broad plan 顺序推进 in_progress / completed

read_element(element_id, reason)
  -> 读取单个已有 HTML 元素
  -> 如果是 table，只返回 table-ref 元信息和列名，不返回表格数据行

read_section(section_id, reason, depth)
  -> 读取某个标题下的章节内容
  -> depth 控制包含的子章节层级

table_extraction(table_id, sql, reason)
  -> 对单张 HTML 表格建立内存 SQLite data 表
  -> 只允许单条 SELECT
  -> 大表拒绝无边界 SELECT *
  -> 返回 rows、evidence_ids、table_audit 和 query_audit

paragraph_extraction(element_id, pattern, reason)
  -> 对文本类元素执行 Python 正则
  -> 返回匹配文本、span 和 evidence ids

set_field(name, value, evidence_ids, reason, status, failure_reason)
  -> 校验字段存在、状态合法、值类型匹配
  -> 校验证据 id 已经被本轮工具观察到
  -> 写入 state.field_states

finish()
  -> 校验所有字段都已 set_field
  -> 校验必填字段、证据完整性和最终一致性
  -> 返回 ok=true 或错误列表
```

工具调用都会写入 `state.actions`，供 replay、route policy 输入组装和测试断言使用。

## 表格观察

`table_extraction` 是当前抽取链路里的表格能力。它不做业务硬编码，只根据 HTML 表格结构和模型给出的 SQL 返回事实。

```text
table_id + SQL
  -> 查找 HtmlTable
  -> 校验 SQL 安全性和大表边界
  -> 计算 table_audit：行列数、空白单元格、重复表头等结构事实
  -> 执行 SQL
  -> 计算 query_audit：返回行数、WHERE 等值列、近似未选中行、输出列空值等查询事实
  -> 返回 rows + evidence_ids + table_audit + query_audit
  -> 同步把摘要写入 action trace
```

`table_audit` 和 `query_audit` 是事实观察，不带 route 结论。resolution 必须在 `set_field.reason` 里解释这些观察对当前字段是否有影响；route policy 后续再结合字段值、证据文本和过程摘要判断是否需要 review。

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
