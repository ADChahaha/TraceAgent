# Agent Service API

这份文档记录 `agent` 服务对 backend 暴露的 HTTP API。更细的模块设计见 [`DESIGN.md`](DESIGN.md)，各阶段内部 Python 契约见对应 `service/*/docs/API.md`。

## 基本工作方式

`agent` HTTP API 按三个业务阶段组织：

```text
backend 持有原始 PDF
  -> POST /v1/document-processor/process
  -> 得到 filename + html

backend 持有已聚合的 HTML
  -> POST /v1/file-extraction-agent/extract
  -> 得到 ExtractionResult(result.fields + trace.fields)
  -> backend 从 trace.fields[].evidence.refs 和 texts 组装 refs_with_text
  -> backend 从 trace.fields[].actions 组装 field_processes
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
RESOLUTION_MODEL
ROUTE_POLICY_MODEL
REASONING_EFFORT
```

`BASE_URL` 和 `OPENAI_API_KEY` 是模型服务连接参数。`RESOLUTION_MODEL` 用于字段抽取；字段抽取的 `REASONING_EFFORT` 默认是 `high`，可用于 DeepSeek 等 OpenAI-compatible 源显式指定思考强度。`ROUTE_POLICY_MODEL` 只用于 route policy 阶段。route policy 不读取通用 `MODEL`，也没有默认模型名；缺少 `ROUTE_POLICY_MODEL` 时会返回 422。

## 健康检查

```text
GET /healthz
```

响应：

```json
{"status": "ok"}
```

## 文档转 HTML

```text
POST /v1/document-processor/process
POST /v1/ocr/process
```

`/v1/ocr/process` 是兼容旧路径的新旧同义入口。

请求类型：`multipart/form-data`

字段：

- `file`：必填，上传的 PDF 文件。
- `file_type`：可选，传 `pdf` 或 `.pdf`；不传时由文件名后缀确认。

处理流程：

```text
UploadFile
  -> route 层包装成可读 file-like 对象
  -> process(file_obj, file_type)
  -> 校验 PDF 类型
  -> convert_pdf_bytes_to_content_list(source_bytes, filename)
  -> build_html_from_content_list(content_list)
  -> build_display_html_from_content_list(content_list)
  -> build_markdown_from_content_list(content_list)
  -> build_blocks_from_content_list(content_list)
  -> ProcessResult(filename, html, display_html, markdown, md_list, blocks, meta_info, warnings)
  -> route 层返回 JSON
```

响应字段：

- `filename`：源文件名，没有源文件名时为 `document.pdf`。
- `html`：抽取友好的语义 HTML fragment，只保留标题、段落、列表、表格等结构，并为关键节点补 `id`。
- `display_html`：供前端 replay iframe 展示的完整 HTML。
- `markdown` / `md_list` / `blocks`：供 backend 保存、证据回填和 trace 展示的标准化文本结构。

示例：

```bash
curl -sS \
  -F 'file=@sample.pdf;type=application/pdf' \
  -F 'file_type=pdf' \
  http://127.0.0.1:8000/v1/document-processor/process
```

失败语义：

- 文件对象不可读、文件类型不是 PDF 或无法确认 PDF 时返回 422。
- MinerU 解析运行时失败时向上返回服务错误。

## 字段抽取

```text
POST /v1/file-extraction-agent/extract
```

请求类型：`application/json`

请求字段：

- `html`：必填，backend 聚合后的 HTML 字符串，元素必须已有稳定 `id`。
- `task_spec`：必填，字段抽取 schema。
- `run_options`：可选，抽取运行预算。
- `model_config`：可选，覆盖字段抽取模型连接配置。
- `base_url`、`api_key` / `openai_api_key`、`resolution_model_name`、`model`、`temperature`、`top_p`、`top_k`、`reasoning_effort`：可选，兼容形式的模型连接覆盖字段；未传 `model_config` 时会组装成同一份 `ModelConfig`。

处理流程：

```text
html + task_spec
  -> route 层解析 JSON
  -> processor.extract(...)
  -> input_adapter 校验 html 非空、task_spec.fields 非空、run_options 合法
  -> html_index 从现有 id 构建 document tree、element/table/row 索引
  -> resolution_new 通过 Reading Stages / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / set_field / finish 定案字段
  -> 返回 ExtractionResult(result + trace)
```

失败语义：

- 缺少 `html`、`task_spec`、`task_spec.fields` 为空、HTML 关键元素缺少 id 或 `run_options.max_tool_calls<=0` 时返回 422。
- 缺少模型连接参数时返回 422。
- resolution 模型阶段失败时，业务结果会收口为 `status=failed` 的 `ExtractionResult`。

## Route Policy 判断

```text
POST /v1/route-policy-agent/evaluate
```

请求类型：`application/json`

请求字段：

- `task_spec`：必填，和抽取阶段一致的字段定义。
- `field_outputs[]`：必填，来自 `ExtractionResult.result.fields`。
- `refs_with_text[]`：必填，backend 从抽取 trace 组装的证据文本。
- `field_processes[]`：必填，backend 从抽取 trace actions 组装的过程摘要。
- `metadata`：可选，调用方透传元信息。
- `base_url`、`openai_api_key`、`model`：可选，覆盖 route policy 模型连接配置；不传 `model` 时读取 `ROUTE_POLICY_MODEL`。
- `structured_output_strategy`：可选，固定只支持 `tool_call`；显式传入 `auto` 或 `json_schema` 会返回 422。

处理流程：

```text
task_spec + field_outputs + refs_with_text + field_processes
  -> route 层解析 JSON
  -> processor.evaluate(...)
  -> input_validator 校验字段名、refs 分组、ref.text 和 field_processes 分组
  -> mapper 合并字段定义、字段输出、证据文本和过程摘要
  -> 必填缺失或抽取过程摘要为空等确定性问题直接 review
  -> query_audit/table_audit 作为事实观察交给 route policy LLM 判断
  -> route policy LLM 输出字段级 accept / review / reject
```

`field_processes` 只传过程摘要和轻量质量诊断。它可以包含
`diagnostics[].quality_type=table_audit|query_audit`、`summary`、`table_id`、`query`
等摘要字段，但不能包含 `status`、工具返回的表格原始行、cell 值或 refs 列表。
