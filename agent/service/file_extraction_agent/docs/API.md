# File Extraction Agent API

这份文档面向调用方，说明 `service.file_extraction_agent` 的 Python 入口、HTTP 入口、请求字段、返回结构和 trace 语义。它只描述对外稳定契约；内部 broad / resolution / tool 的实现细节见 [`DESIGN.md`](DESIGN.md)。

## 基本链路

`service.file_extraction_agent` 不接收原始 PDF / DOCX，也不负责 OCR。调用方必须先把文档处理成标准化 blocks，再把 blocks 和显式 `task_spec` 交给本包：

```text
backend / service.document_processor 产出标准化 blocks
  -> 调用方为每个 block 生成稳定唯一 block_id
  -> 调用方选择并传入显式 task_spec
  -> service.file_extraction_agent.processor.extract(...)
  -> input_adapter 校验 task_spec、block_id 必填和唯一性
  -> broad extraction 预选字段证据
  -> resolution 逐字段定案，必要时按模型请求调用工具
  -> validation_rules / FieldDefinition 约束后处理
  -> ExtractionResult(status + result + trace)
```

`result` 只放最终字段值；`trace` 保存证据、工具动作、规则动作和失败原因，供后续治理层判断是否入库、转人工或拒绝。

## Python 入口

入口函数：

```python
from service.file_extraction_agent.processor import extract

result = extract(
    *,
    blocks,
    markdown="",
    md_list=None,
    task_spec,
    run_options=None,
    metadata=None,
    base_url=None,
    openai_api_key=None,
    model=None,
    structured_output_strategy="auto",
    extractor_client=None,
)
```

调用步骤：

```text
blocks + task_spec
  -> extract(...)
  -> 如果 extractor_client 已传入，直接使用
  -> 否则读取显式 base_url/openai_api_key/model 或环境变量 BASE_URL/OPENAI_API_KEY/MODEL
  -> MODEL 仍为空时使用代码默认模型
  -> 返回 ExtractionResult
```

最小示例：

```python
from service.file_extraction_agent.processor import extract
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


blocks = [
    NormalizedBlock(
        document_id="doc-1",
        block_id="doc-1:p1:b1",
        page_no=1,
        text="发票号码：INV-001",
    )
]

task_spec = TaskSpec(
    task_name="invoice",
    fields=[
        FieldDefinition(
            field_name="invoice_no",
            display_name="发票号",
            type="string",
            required=True,
        )
    ],
)

result = extract(
    blocks=blocks,
    task_spec=task_spec,
    base_url="https://llm.example.com/v1",
    openai_api_key="your-api-key",
    model="gpt-compatible-model",
)
```

## HTTP 入口

路径：

```text
POST /v1/file-extraction-agent/extract
```

请求体由 `routes.file_extraction_agent.ExtractRequest` 解析。未知字段会被拒绝。

请求示例：

```json
{
  "blocks": [
    {
      "document_id": "doc-1",
      "block_id": "doc-1:p1:b1",
      "text": "发票号码：INV-001",
      "page_no": 1,
      "kind": "text",
      "meta_info": {}
    }
  ],
  "markdown": "发票号码：INV-001",
  "md_list": ["发票号码：INV-001"],
  "task_spec": {
    "task_name": "invoice",
    "fields": [
      {
        "field_name": "invoice_no",
        "display_name": "发票号",
        "type": "string",
        "required": true
      }
    ]
  },
  "run_options": {
    "allow_extra_lookup": true,
    "max_lookup_calls_per_field": 1,
    "lookup_top_k": 3,
    "max_prompt_blocks": 200,
    "max_prompt_block_chars": 2000,
    "max_resolution_evidence_fields": 80,
    "max_prompt_evidence_text_chars": 1000
  },
  "metadata": {
    "source": "backend"
  },
  "base_url": "https://llm.example.com/v1",
  "openai_api_key": "your-api-key",
  "model": "gpt-compatible-model",
  "structured_output_strategy": "auto"
}
```

HTTP 错误语义：

- 请求 JSON 形状不符合 Pydantic schema：FastAPI 返回 `422`。
- 缺少显式 `task_spec`、缺少或重复 `block_id`、模型连接参数不完整：route 层返回 `422`。
- broad / resolution 运行中模型 API、结构化输出或节点校验失败：HTTP 仍返回 `200`，响应体中 `ExtractionResult.status="failed"`，并在 `failure_reason` 和 `trace` 中记录失败原因。

## 输入字段

### blocks

`blocks` 是必填主输入，类型是 `list[NormalizedBlock]`。

每个 block 至少需要：

- `document_id`：文档 id。
- `block_id`：调用方生成的稳定唯一 id。本包不自动生成、不从 `meta_info.block_id` 兜底读取；缺失或重复会报错。
- `text`：标准化后的块文本。

可选字段：

- `page_no`：页码。
- `bbox`：坐标框，结构为 `x0/y0/x1/y1`。
- `kind`：块类型，默认是 `text`。
- `meta_info`：调用方保留的额外元信息。

### task_spec

`task_spec` 必须显式传入。本包不维护本地 `task_specs/` 目录，也不支持 `task_spec_name`。

字段定义：

```json
{
  "field_name": "invoice_no",
  "display_name": "发票号",
  "type": "string",
  "required": true,
  "critical": false,
  "allow_missing": false,
  "validation_rules": {},
  "cross_field_hints": [],
  "lookup_hints": [],
  "enum_values": []
}
```

支持的 `type`：

- `string`
- `date`
- `enum`
- `money`
- `boolean`
- `list`：字符串列表，适合论文题名、房间号、名单条目等多值字段；resolution 的 resolved `value` 必须是 `string[]`，不能用分隔符拼成单个字符串。

### run_options

`run_options` 控制运行策略和 prompt 预算。Python 入口和 HTTP 入口都支持，
并按公开契约 `RunOptions` 解析；内部 graph 也复用这一份运行配置。

- `allow_extra_lookup`：是否允许 resolution 模型请求全局补查。
- `max_lookup_calls_per_field`：每个字段最多允许几次全局补查。
- `lookup_top_k`：每次全局补查最多返回几个 blocks。
- `max_prompt_blocks`：broad prompt 最多携带多少个 blocks。
- `max_prompt_block_chars`：broad prompt 单个 block 文本最多保留多少字符。
- `max_resolution_evidence_fields`：resolution prompt 最多携带多少个字段 evidence；目标字段优先保留。
- `max_prompt_evidence_text_chars`：resolution prompt 单条 evidence 文本最多保留多少字符。
- `keep_detailed_trace`：预留开关；当前对外 trace 不包含 raw prompt 或 raw model response。

## validation_rules

`validation_rules` 只在模型完成字段定案之后执行，用于通用规则校验、规则覆盖或跨字段一致性收口。

当前支持：

- `source_type=table_rows`
  - 按 `columns`、`filter`、`exclude`、`target_column` 从标准化表格行筛选证据。
  - 如果命中行的 `target_column` 全为空，会保留模型原始定案，不会覆盖成空 resolved。
  - 覆盖时会记录 `validation_rule` action。
- `operation=count_items`
  - 按 `source_field` 的已定案结果计算条目数量。
  - 会记录 `validation_rule` action。

示例：

```json
{
  "source_type": "table_rows",
  "columns": ["楼栋", "房间", "平均分", "模范/文明"],
  "target_column": "房间",
  "filter": {"column": "模范/文明", "equals": "文明寝室"},
  "exclude": [{"column": "模范/文明", "equals": "模范寝室"}],
  "output": {
    "separator": ",",
    "deduplicate": true
  }
}
```

## 返回结构

成功完成整包流程时：

```json
{
  "status": "completed",
  "failure_reason": null,
  "result": {
    "fields": [
      {
        "field_name": "invoice_no",
        "status": "resolved",
        "value": "INV-001"
      }
    ]
  },
  "trace": {
    "fields": [
      {
        "field_name": "invoice_no",
        "status": "resolved",
        "evidence": {
          "block_ids": ["doc-1:p1:b1"],
          "texts": ["发票号码：INV-001"],
          "refs": [
            {
              "document_id": "doc-1",
              "page": 1,
              "span": null,
              "block_id": "doc-1:p1:b1"
            }
          ],
          "status": "model_resolved",
          "notes": ["按模型 used_block_ids 从标准化 blocks 绑定证据"]
        },
        "related_fields": [],
        "actions": [],
        "reason": "字段已定案",
        "failure_reason": null
      }
    ],
    "warnings": [],
    "metadata": {}
  }
}
```

整包失败时：

```text
ExtractionResult.status = "failed"
ExtractionResult.failure_reason = "broad_extraction 执行失败: ..."
result.fields[] = 按 task_spec 字段补齐 failed 结果
trace.fields[].actions[] = 包含 model_call_error
trace.metadata.failure_stage = broad_extraction / resolution / graph_mapping
```

字段级失败时：

```text
result.fields[i].status = "failed"
result.fields[i].value = null
trace.fields[i].failure_reason = 字段失败原因
```

## trace 字段

对外稳定 trace 保存在 `ExtractionResult.trace`：

```text
trace
  -> fields[]
       -> field_name
       -> status
       -> evidence
            -> block_ids
            -> texts
            -> refs
            -> status
            -> notes
       -> related_fields
       -> actions[]
            -> action_type
            -> message
            -> refs
            -> used_in_final_decision
            -> metadata
       -> reason
       -> failure_reason
  -> warnings
  -> metadata
```

常见 `actions[].action_type`：

- `field_reference`：模型请求读取其他字段的 evidence bundle。
- `global_lookup`：模型请求从全量 blocks 补查证据。
- `validation_rule`：系统按 `validation_rules` 覆盖或校正模型结果。
- `field_constraint`：系统按字段基础约束把 resolved 降级为 failed。
- `model_call_error`：broad 或 resolution 运行中发生模型调用或结构化输出错误。

`used_in_final_decision` 表示该 action 的证据是否支撑最终定案。validation 覆盖最终 evidence 后，lookup action 会按最终 evidence 重新计算这个标记。

当前 trace 边界：

- 保留字段级证据、refs、相关字段、工具动作、规则动作、失败原因。
- 不对外保留 raw prompt、raw model response 或完整内部 broad 原始对象。
- `keep_detailed_trace` 是预留运行选项，当前不改变对外返回结构。

## 配置

如果没有显式传入 `extractor_client`，模型连接参数按下面顺序解析：

```text
extract(...) / HTTP request 显式参数
  -> 环境变量 BASE_URL / OPENAI_API_KEY / MODEL
  -> MODEL 仍为空时使用代码默认模型
```

必需：

- `base_url` 或 `BASE_URL`
- `openai_api_key` 或 `OPENAI_API_KEY`

可选：

- `model` 或 `MODEL`
- `structured_output_strategy`：`auto`、`json_schema` 或 `tool_call`

`structured_output_strategy="auto"` 时，系统先尝试 `json_schema`；只有结构化协议明确不支持时才尝试 `tool_call`。如果结构化 runnable 已经开始调用后发生超时、鉴权、服务端错误或输出校验失败，抽取端不会换协议重试，而是按模型调用失败进入统一失败收口。

## 不支持的输入

- 不支持直接传 PDF / DOCX 文件对象。
- 不支持 `task_spec_name`。
- 不支持缺失 `block_id` 的 blocks。
- 不支持重复 `block_id` 的 blocks。
- 不保证 `meta_info.block_id` 会被读取；调用方应把 id 写在 `block.block_id`。
