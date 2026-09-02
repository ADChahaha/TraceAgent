# Agent Service API

这份文档记录 `agent` 服务当前对 backend 暴露的 HTTP 能力：PDF/DOCX 文档标准化和多文档 QA chat completion。更细的模块设计见 [`DESIGN.md`](DESIGN.md)。

## 1. 基本工作方式

```text
backend 持有原始 PDF/DOCX
  -> POST /v1/document-processor/process（file_type 判定 pdf/docx）
  -> 得到 filename + html
  -> backend 保存文档和对话状态

backend 持有 documents(filename + html) + append-only messages
  -> POST /v1/document-qa/chat/completions
  -> 持续得到 completion.created / source_indexed / model_message / tool_* / completion.*
  -> backend 入库并转发给前端
```

agent 不保存多轮 conversation；每一轮 QA 都由 backend 把 documents 和 append-only messages 重新传入。这里没有 memory/summary 通路，避免每轮重写上下文破坏 provider prompt cache。

## 2. 运行前提

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
MODEL
MODEL_API_TRANSPORT
```

`MODEL_API_TRANSPORT` 只支持 `responses` 或 `chat_completions`，默认 `responses`；它决定同一轮 provider attempt 只走 Responses API 还是只走 chat/completions，不做跨 API 自动 fallback。可选参数包括 `TEMPERATURE`、`TOP_P`、`TOP_K`、`REASONING_EFFORT`、`MODEL_MAX_RETRIES` 和 `MODEL_REQUEST_TIMEOUT`。

## 3. 健康检查

```text
GET /healthz
```

响应：

```json
{"status": "ok"}
```

## 4. 文档转 HTML

```text
POST /v1/document-processor/process
```

请求类型：`multipart/form-data`

字段：

- `file`：必填，上传的 PDF 或 DOCX 文件。
- `file_type`：可选，传 `pdf`/`.pdf` 或 `docx`/`.docx`；不传时由文件名后缀确认。

处理流程：

```text
PDF/DOCX UploadFile
  -> route 层包装成可读 file-like 对象
  -> process(file_obj, file_type)  统一入口，file_type 分流（缺省看后缀）
  -> PDF 走 MinerU：pdf.convert_pdf_to_html(...)（内部 converter -> html）
  -> DOCX 走 python-docx：Document(BytesIO(...)) 按 body 顺序遍历 paragraph/table
  -> 生成带 CSS 的完整 HTML 文档
  -> ProcessResult(filename, html)
  -> route 层返回 JSON
```

失败语义：

- 文件对象不可读、PDF 文件类型不是 PDF 或无法确认 PDF 时返回 422。
- 解析运行时失败时向上返回服务错误。

## 5. 多文档 QA Chat Completion

```text
POST /v1/document-qa/chat/completions
```

请求类型：`application/json`

响应类型：`text/event-stream`

### 请求字段

- `completion_id`：必填，由 backend 生成的本轮 completion id。
- `documents[]`：必填，每个元素包含 `filename` 和 `html`。
- `messages[]`：必填，多轮对话消息，role 支持 `system` / `user` / `assistant` / `tool`，`content` 必须非空；backend 只追加新消息和工具结果，不自动裁剪或摘要。
- `stream`：当前可传，但第一版总是返回 SSE。
- `metadata`：可选，agent 目前不持久化；backend 可用于调试或未来扩展。
- `run_options`：可选，目前支持 `max_tool_calls`，必须大于 0。
- `model_config`：可选，覆盖模型连接配置。
- 扁平模型字段：`base_url`、`api_key` / `openai_api_key`、`model`、`api_transport`、`temperature`、`top_p`、`top_k`。

示例：

```json
{
  "completion_id": "cmp_456",
  "documents": [
    {
      "filename": "contract.pdf",
      "html": "<h1>Agreement</h1><h2>Termination</h2><p>Either party may terminate...</p>"
    }
  ],
  "messages": [
    {"role": "user", "content": "这份合同可以提前终止吗？"}
  ],
  "stream": true,
  "metadata": {"task_id": "task_001", "turn_id": "turn_003"},
  "run_options": {"max_tool_calls": 80}
}
```

### 处理流程

```text
ChatCompletionRequest
  -> route 层解析 JSON，禁止未知字段
  -> processor.create_completion_stream(...)
  -> input_adapter 校验 completion_id/documents/messages/run_options
  -> html_index 把多份 HTML 落盘成真实文件树（DocumentFileTree）
  -> graph 先输出 completion.created 和 source_indexed（workspace_root + tree）
  -> resolution_new 构建 QA prompt，暴露 ls / grep / read
  -> 模型边回答边调用工具，过程消息用真实 .md 文件路径 Markdown link 引用证据
  -> 无 tool_calls 且 provider terminal stop signal 的 model_message 带 is_final=true
  -> graph 输出 completion.completed / completion.failed
  -> processor 若收到 cancel flag，则输出 completion.cancelled
```

### SSE 事件

常见事件：

- `completion.created`
- `source_indexed`
- `model_message`
- `tool_started`
- `tool_completed`
- `tool_failed`
- `completion.completed`
- `completion.cancelled`
- `completion.failed`

示例：

```text
event: completion.created
data: {"seq":1,"id":"cmp_456","type":"completion.created","status":"in_progress"}

event: source_indexed
data: {"seq":2,"type":"source_indexed","tool":"source_index","result":{"ok":true,"workspace_root":"/tmp/qa_workspace/cmp_456","tree":["└── 0001-contract/"]}}

event: model_message
data: {"seq":4,"type":"model_message","content":"我先查看 Termination 章节。[Termination](/tmp/qa_workspace/cmp_456/0001-contract/0001-Termination)","tool_call_count":1,"tool_calls":[{"name":"read","args":{"path":"/tmp/qa_workspace/cmp_456/0001-contract/0001-Termination/0001-termination.md"}}],"is_final":false}

event: model_message
data: {"seq":11,"type":"model_message","content":"可以提前终止。[任一方可以终止](/tmp/qa_workspace/cmp_456/0001-contract/0001-Termination/0001-termination.md)","tool_call_count":0,"tool_calls":[],"is_final":true,"stop_signal":"stop"}

event: completion.completed
data: {"seq":12,"id":"cmp_456","type":"completion.completed","status":"completed"}
```

### 证据规则

- `grep` 只是候选搜索（rg 原样 stdout），不能单独作为最终事实依据。
- `read` 读取一个 `.md` block 文件，用于理解上下文。
- `model_message` 中首次陈述具体事实时，应使用真实文件路径的 Markdown evidence link，例如 `[任一方可以终止](/abs/path/.../0001-termination.md)`。

## 6. 查询 completion

```text
GET /v1/document-qa/chat/completions/{completion_id}
```

当前实现是占位调试接口：

```json
{"status": "not_implemented"}
```

后续如果需要查询 active runtime，可在不改变 backend 作为持久化事实来源的前提下扩展。

## 7. 取消 completion

```text
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

处理流程：

```text
completion_id
  -> processor.cancel_completion(completion_id)
  -> 在 _ACTIVE_COMPLETIONS 中查找 active runtime
  -> 找到则设置 cancel_requested=true、status=cancelling
  -> create_completion_stream 的 SSE consumer 立即输出 completion.cancelled 并关闭 SSE
  -> producer 若稍后从 provider 返回事件，会在 runtime 已关闭时丢弃
  -> 找不到则返回 not_found
```

示例响应：

```json
{"id": "cmp_456", "status": "cancelling"}
```

或：

```json
{"id": "cmp_456", "status": "not_found"}
```

## 8. 已删除旧接口

本分支不再暴露旧字段抽取入口：

```text
POST /v1/file-extraction-agent/extract/stream
```

也不再接收 `task_spec`，不再输出 `result_completed` 字段结果事件。
