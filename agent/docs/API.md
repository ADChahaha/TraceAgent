# Agent Service API

这份文档记录 `agent` 服务当前对 backend 暴露的两个 HTTP 阶段：文档标准化和字段抽取。更细的模块设计见 [`DESIGN.md`](DESIGN.md)。

## 基本工作方式

```text
backend 持有原始 PDF
  -> POST /v1/document-processor/process
  -> 得到 filename + html

backend 持有 documents(filename + html)
  -> POST /v1/file-extraction-agent/extract/stream
  -> 持续得到 tool_started / tool_completed / tool_failed / field_written / result_completed
  -> backend 从 result_completed.result.fields 直接决定哪些字段可提交
```

## 运行前提

在 `agent/` 目录启动服务：

```bash
conda activate agent-gate
set -a; source .env; set +a
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

模型调用需要 `.env` 或运行环境提供：

```text
BASE_URL
OPENAI_API_KEY
RESOLUTION_MODEL
```

这里没有 `ROUTE_POLICY_MODEL`。

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

- `filename`
- `html`
- `display_html`
- `markdown` / `md_list` / `blocks`

失败语义：

- 文件对象不可读、文件类型不是 PDF 或无法确认 PDF 时返回 422
- 解析运行时失败时向上返回服务错误

## 字段抽取

```text
POST /v1/file-extraction-agent/extract/stream
```

请求类型：`application/json`

响应类型：`application/x-ndjson`

请求字段：

- `documents[]`：必填，每个元素包含 `filename` 和 `html`
- `task_spec`：必填，字段抽取 schema
- `run_options`：可选，抽取运行预算
- `model_config`：可选，覆盖字段抽取模型连接配置

处理流程：

```text
documents + task_spec
  -> route 层解析 JSON
  -> processor.extract_stream(...)
  -> input_adapter 校验 documents 非空、filename/html 非空、task_spec.fields 非空、run_options 合法
  -> html_index 生成 /001-filename-title/... 虚拟文件树、path 索引、list item 编号和 table row 编号
  -> resolution_new 通过 tree / read / add_candidate_evidence / review_evidences / write_field / submit_result 定案字段
  -> graph 按顺序输出 NDJSON 工具事件，最后输出 result_completed
```

NDJSON 事件：

- `tool_started`
- `tool_completed`
- `tool_failed`
- `candidate_evidence_added`
- `field_written`
- `result_completed`

失败语义：

- 缺少 `documents`、`documents[].filename`、`documents[].html`、`task_spec`、`task_spec.fields` 为空或 `run_options.max_tool_calls<=0` 时返回 422
- 缺少模型连接参数时返回 422
- resolution 模型阶段失败时，stream 会输出失败事件，并以 `result_completed` 收口失败结果
