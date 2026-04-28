# Agent Service API

这份文档记录 `agent` 服务对 backend 暴露的 HTTP API。更细的模块设计见
[`DESIGN.md`](DESIGN.md)，各阶段内部
Python 契约见对应 `service/*/docs/API.md`。

## 基本工作方式

`agent` HTTP API 按三段处理链路组织：

```text
backend 持有原始 PDF / DOCX
  -> POST /v1/document-processor/process
  -> 得到 markdown、md_list、blocks
  -> backend 在 session 维度补齐 document_id 和稳定 block_id
  -> POST /v1/file-extraction-agent/extract
  -> 得到 ExtractionResult(result.fields + trace.fields)
  -> backend 从 trace.fields[].evidence.refs 和 texts 组装 refs_with_text
  -> POST /v1/route-policy-agent/evaluate
  -> 得到 RoutePolicyResult(field_routes[])
```

route 层只做 HTTP 协议适配，业务处理分别交给：

- `service.document_processor.processor.process(...)`
- `service.file_extraction_agent.processor.extract(...)`
- `service.route_policy_agent.processor.evaluate(...)`

## 运行前提

在 `agent/` 目录启动服务：

```bash
conda activate agent-gate
set -a; source .env; set +a
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

模型调用需要 `.env` 或运行环境提供：

```text
BASE_URL
OPENAI_API_KEY
MODEL
```

`MODEL` 如果缺失，代码会使用默认模型；`BASE_URL` 和 `OPENAI_API_KEY`
缺失时，抽取和 route policy 阶段会返回 422。

## 健康检查

```text
GET /healthz
```

响应：

```json
{"status": "ok"}
```

## 文档标准化

```text
POST /v1/document-processor/process
POST /v1/ocr/process
```

`/v1/ocr/process` 是兼容旧路径的新旧同义入口。

请求类型：`multipart/form-data`

字段：

- `file`：必填，上传的 `pdf` 或 `docx` 文件。
- `file_type`：可选，传 `pdf` 或 `docx`；不传时由文件名或内容类型推断。

处理流程：

```text
UploadFile
  -> route 层包装成可读 file-like 对象
  -> process(file_obj, file_type)
  -> PDF 走 docling + RapidOCR，DOCX 走 python-docx
  -> 输出 ProcessResult
  -> route 层返回 JSON
```

响应字段：

- `file_type`：实际处理的文件类型。
- `filename`：源文件名。
- `md_list`：分段 markdown 列表。
- `markdown`：整篇 markdown。
- `blocks[]`：标准化内容块。
  - `text`
  - `page_no`
  - `bbox`
  - `kind`
  - `meta_info`
- `meta_info`：处理器元信息。
- `warnings`：非阻断告警。

示例：

```bash
curl -sS \
  -F 'file=@sample.pdf;type=application/pdf' \
  -F 'file_type=pdf' \
  http://127.0.0.1:8000/v1/document-processor/process
```

失败语义：

- 文件对象不可读、文件类型不支持或无法推断时返回 422。
- PDF / DOCX 解析运行时失败时向上返回服务错误。

## 字段抽取

```text
POST /v1/file-extraction-agent/extract
```

请求类型：`application/json`

请求字段：

- `blocks[]`：必填，backend 聚合后的标准化 blocks。
  - `document_id` 必填。
  - `block_id` 必填，且必须在本次请求内唯一。
  - `text` 必填。
  - `page_no`、`bbox`、`kind`、`meta_info` 可选。
- `markdown`：可选，整篇 markdown。
- `md_list`：可选，markdown 分段。
- `task_spec`：必填，字段抽取 schema。
- `run_options`：可选，抽取运行预算。
- `metadata`：可选，调用方透传元信息。
- `base_url`、`openai_api_key`、`model`：可选，覆盖环境变量里的模型连接配置。
- `structured_output_strategy`：可选，`auto`、`json_schema` 或 `tool_call`。

`task_spec.fields[]` 常用字段：

- `field_name`
- `display_name`
- `type`：`string`、`date`、`enum`、`money`、`boolean`
- `required`
- `critical`
- `allow_missing`
- `validation_rules`
- `lookup_hints`
- `enum_values`

处理流程：

```text
blocks + markdown + task_spec
  -> route 层解析 JSON
  -> processor.extract(...)
  -> input_adapter 校验 block_id 必填唯一并组装 ExtractionInput
  -> broad extraction 为每个字段预选 evidence
  -> resolution 对每个字段输出 resolved / failed
  -> validation_rules 和基础字段约束做确定性后处理
  -> 返回 ExtractionResult(result + trace)
```

响应字段：

- `status`：`completed` 或 `failed`。
- `failure_reason`：失败时的顶层原因。
- `result.fields[]`：最终字段值。
  - `field_name`
  - `status`
  - `value`
- `trace.fields[]`：证据和定案留痕。
  - `field_name`
  - `status`
  - `evidence.block_ids`
  - `evidence.texts`
  - `evidence.refs`
  - `reason` / `failure_reason`
- `trace.warnings`
- `trace.metadata`

示例：

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  --data-binary @extraction_payload.json \
  http://127.0.0.1:8000/v1/file-extraction-agent/extract
```

失败语义：

- 缺少 `task_spec`、block 缺少 `block_id`、`block_id` 重复时返回 422。
- 缺少模型连接参数时返回 422。
- broad / resolution 模型阶段失败时，业务结果会收口为 `status=failed`
  的 `ExtractionResult`，并在 trace metadata 中记录失败阶段。

## Route Policy 判断

```text
POST /v1/route-policy-agent/evaluate
```

请求类型：`application/json`

请求字段：

- `task_spec`：必填，和抽取阶段一致的字段定义。
- `field_outputs[]`：必填，来自 `ExtractionResult.result.fields`。
  - `field_name`
  - `status`
  - `value`
- `refs_with_text[]`：必填，backend 从抽取 trace 组装的证据文本。
  - `field_name`
  - `refs[]`
    - `document_id`
    - `page`
    - `block_id`
    - `span`
    - `text`
- `policy_options`：可选，route prompt 的 refs 数量和文本长度预算。
- `metadata`：可选，调用方透传元信息。
- `base_url`、`openai_api_key`、`model`：可选，覆盖环境变量里的模型连接配置。
- `structured_output_strategy`：可选，`auto`、`json_schema` 或 `tool_call`。

处理流程：

```text
task_spec + field_outputs + refs_with_text
  -> route 层解析 JSON
  -> processor.evaluate(...)
  -> RoutePolicyInput 拒绝 trace/actions/额外风险标记等未知字段
  -> input_validator 校验字段名、refs 分组、ref.text 和来源位置
  -> mapper 合并 FieldDefinition、RouteFieldOutput、EvidenceTextRef[]
  -> failed + critical/required 字段直接 reject
  -> resolved 字段调用小 LLM 输出 RoutePolicyDecision
  -> 返回 RoutePolicyResult(field_routes[])
```

响应字段：

- `status`：`completed` 或 `failed`。
- `failure_reason`：失败时的顶层原因。
- `field_routes[]`
  - `field_name`
  - `route`：`accept`、`review` 或 `reject`
  - `route_reason`
  - `needs_review`
- `warnings`
- `metadata`

示例：

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  --data-binary @route_policy_payload.json \
  http://127.0.0.1:8000/v1/route-policy-agent/evaluate
```

失败语义：

- 未知字段、缺少 `refs_with_text`、ref 缺少 `text` 或来源位置时返回 422。
- 缺少模型连接参数时返回 422。
- 小 LLM 结构化输出调用失败时返回 502。

## 全流程组装注意事项

`document_processor` 不负责生成 `document_id` 和稳定 `block_id`。backend 在调用
`file_extraction_agent` 前需要补齐这些字段：

```text
ProcessResult.blocks[]
  -> 为每个 block 写入 document_id
  -> 为每个 block 写入本次 session 内稳定唯一 block_id
  -> 作为 extract.blocks[] 传入
```

`route_policy_agent` 不读取抽取 trace，也不读取完整原文。backend 需要把抽取
trace 中的证据位置和证据文本合并成 `refs_with_text`：

```text
ExtractionResult.result.fields[]
  -> field_outputs[]

ExtractionResult.trace.fields[].evidence.refs + evidence.texts
  -> 按 field_name 对齐
  -> refs_with_text[].refs[].text 填入对应 evidence text
  -> refs_with_text[].refs[] 保留 document_id / page / block_id / span
```

## 已验证样例

使用真实 PDF `18【本科生】2025-2026学年第一学期 文明模范寝室.pdf`
走 HTTP 全流程，结果如下：

```text
/v1/document-processor/process -> 200
/v1/file-extraction-agent/extract -> 200
/v1/route-policy-agent/evaluate -> 200
```

抽取字段：

```text
notice_title = 【本科生】2025-2026学年第一学期 文明模范寝室
model_dorm_rooms = 106、218、413、521、603
civilized_dorm_rooms = 212、214、302、324、401、518、519、523、614、618、620、621
building_average_score = 85.1
```

route policy 均返回 `accept`。
