# File Extraction Agent API

这份文档面向调用方，说明 `service.file_extraction_agent` 的 Python 入口、HTTP 入口、请求字段、返回结构和 trace 语义。它只描述对外稳定契约；内部 broad / resolution / tool 的实现细节见 [`DESIGN.md`](DESIGN.md)。

## 基本链路

`service.file_extraction_agent` 不接收原始 PDF / DOCX，也不负责 OCR。调用方必须先把文档处理成标准化 blocks，再把 blocks 和显式 `task_spec` 交给本包：

```text
backend / service.document_processor 产出标准化 blocks
  -> 调用方为每个 block 生成稳定唯一 block_id
  -> 调用方选择并传入显式 task_spec
  -> service.file_extraction_agent.processor.extract(...)
  -> input_adapter 调用 block_contract 校验 task_spec 和 blocks 契约
  -> 共享 broad loop 通过 search_grep、add_broad_candidate 和 copy_field_candidates 写入候选池
  -> 共享 resolution loop 读取/补充候选，必要时用 count_field_candidates 统计候选数量
  -> graph 用 candidate_id 回查 ref、block_id、document_id 和 page_no
  -> ExtractionResult(status + result + trace)
```

`result` 只放最终字段值；`trace` 保存候选证据、工具动作和失败原因，供后续治理层判断是否入库、转人工或拒绝。

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
    broad_model=None,
    resolution_model=None,
    structured_output_strategy="tool_call",
    extractor_client=None,
    broad_extractor_client=None,
    resolution_extractor_client=None,
)
```

调用步骤：

```text
blocks + task_spec
  -> extract(...)
  -> 如果 extractor_client 或阶段客户端已传入，优先使用
  -> 否则读取显式 base_url/openai_api_key/model 或环境变量 BASE_URL/OPENAI_API_KEY/MODEL
  -> broad_model / resolution_model 可分别覆盖两个阶段的模型名
  -> structured_output_strategy 固定为 tool_call，底层映射到 LangChain function_calling
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
    "max_prompt_blocks": 200,
    "max_prompt_block_chars": 2000,
    "max_resolution_candidates": 20,
    "max_broad_iterations": 8,
    "max_resolution_iterations": 8,
    "keep_detailed_trace": false
  },
  "metadata": {
    "source": "backend"
  },
  "base_url": "https://llm.example.com/v1",
  "openai_api_key": "your-api-key",
  "model": "gpt-compatible-model",
  "structured_output_strategy": "tool_call"
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

- `max_prompt_blocks`：broad prompt 最多展示多少个可搜索段落样例。
- `max_prompt_block_chars`：broad prompt 单个段落样例最多保留多少字符。
- `max_resolution_candidates`：resolution prompt 最多携带多少个候选证据。
- `max_broad_iterations`：每字段 broad 预算；runner 会乘以字段数作为共享 broad loop 最大动作轮次。
- `max_resolution_iterations`：每字段 resolution 预算；runner 会乘以字段数作为共享 resolution loop 最大动作轮次。
- `keep_detailed_trace`：预留开关；当前对外 trace 不包含 raw prompt 或 raw model response。

## 字段提示

`validation_rules`、`lookup_hints`、`cross_field_hints` 和 `enum_values` 会随字段定义进入模型上下文。当前实现不维护独立规则后处理阶段；字段结果是否可自动通过，应交给后续 `route_policy_agent` 根据字段输出和 refs 文本判断。

## result 与 trace 边界

`ExtractionResult` 按“业务结果”和“证据留痕”分层返回：

```text
ExtractionResult
  -> status / failure_reason
  -> result.fields[]
       -> field_name
       -> status
       -> value
  -> trace.fields[]
       -> field_name
       -> status
       -> evidence
       -> actions
       -> related_fields
       -> reason / failure_reason
```

设计约束：

- `result.fields[]` 是纯业务输出，不重复放 evidence、actions 或 prompt 调试信息。
- `trace.fields[].evidence` 是支撑最终值的候选证据摘要，来自 `final_decision.candidate_ids` 回查。
- `trace.fields[].actions` 是系统可证明发生过的工具动作，包含 `search_grep`、候选写入、`count_field_candidates`、`copy_field_candidates`、`finish_broad` 和 `final_decision`。
- 调用方展示或入库字段值时读 `result`；需要高亮原文、解释定案、转人工或做 route policy 时读 `trace`。

例如抽取“作品类型为学术论文的论文题目和数量”时，`result` 应只返回论文题名列表和数量；每个题名对应的表格行、页码、block_id、搜索 query 和候选写入动作都放在 `trace`。

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
              "span": "p:p1",
              "block_id": "doc-1:p1:b1"
            }
          ],
          "status": "candidate_resolved",
          "notes": ["field decision referenced candidate_ids: c1"]
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
ExtractionResult.failure_reason = "broad 执行失败: ..."
result.fields[] = 按 task_spec 字段补齐 failed 结果
第一个未完成字段的 trace.actions[] 包含 model_call_error
trace.metadata.failure_stage = broad / resolution
trace.metadata.completed_field_names = 失败前已完成字段
trace.metadata.pending_field_names = 失败时仍未完成字段
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

- `search_grep`：模型请求一次性在文本段落索引和表格行索引中做关键词检索；多关键词 query 固定使用 `term1 OR term2 OR term3`。
- `add_broad_candidate`：broad 阶段把 grep ref 写入候选池。
- `copy_field_candidates`：broad 阶段把来源字段候选复制到目标字段；工具结果只返回复制数量和 candidate id，不返回候选正文。
- `add_resolution_candidate`：resolution 阶段把二次检索 ref 或工具返回的数字/字符串写入候选池。
- `count_field_candidates`：resolution 阶段统计指定字段当前候选数量；返回 number，不返回候选正文或 refs。
- `get_candidate_bundle`：resolution 阶段读取指定字段候选池。
- `finish_broad`：broad 阶段结束指定字段召回。
- `final_decision`：resolution 阶段输出字段最终定案。
- `model_call_error`：broad 或 resolution 运行中发生模型调用或结构化输出错误。

`used_in_final_decision` 表示该 action 的候选证据是否支撑最终定案。

当前 trace 边界：

- 保留字段级证据、refs、相关字段、工具动作、失败原因。
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
- `broad_model`：只用于 broad 候选召回阶段。
- `resolution_model`：只用于 resolution 字段定案阶段。
- 未配置阶段模型时，对应阶段复用 `model` 或 `MODEL` 构造出的共享客户端。
- `structured_output_strategy`：固定只支持 `tool_call`，未传时默认也是 `tool_call`。

`tool_call` 在客户端内部映射到 LangChain 的 `function_calling`。HTTP 入口显式传入 `json_schema` 或 `auto` 会在请求解析阶段返回 `422`；Python 入口显式传入这些旧策略时，客户端构造阶段会抛出配置错误。结构化 runnable 调用失败后不会再解析裸 JSON 或裸 tool call 参数，而是按模型调用失败进入统一失败收口。

## 不支持的输入

- 不支持直接传 PDF / DOCX 文件对象。
- 不支持 `task_spec_name`。
- 不支持缺失 `block_id` 的 blocks。
- 不支持重复 `block_id` 的 blocks。
- 不保证 `meta_info.block_id` 会被读取；调用方应把 id 写在 `block.block_id`。
