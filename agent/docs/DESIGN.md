# Agent Service Design

这份文档描述 `agent service` 当前保留的两个能力：`document_processor` 和 `file_extraction_agent`。其中 `document_processor` 负责把上传 PDF/DOCX 标准化成语义 HTML；`file_extraction_agent` 在 `dev-qa` 分支上已经重构为多文档 QA chat completion agent，负责对 backend 提供的一组 HTML 文档进行可追溯问答。

`agent service` 不访问 backend SQLite，不持久化多轮会话，也不决定前端任务状态。backend 是 task、append-only messages、events 和 replay 的持久化事实来源；agent 只执行一次 completion，并通过 SSE 返回过程事件。跨轮上下文由 backend 组装成 OpenAI 风格 chat messages，包含 `user`、`assistant` 的 `tool_calls` 和 `tool` 消息。

## 1. 目标

`agent/` 的目标是把“原始文件处理”和“文档 QA 执行”拆开：

```text
原始 PDF/DOCX
  -> document_processor 标准化为 html / display_html / markdown / blocks
  -> backend 保存文档和对话状态
  -> file_extraction_agent 接收 documents + append-only messages
  -> agent 像 code agent 浏览代码仓库一样 ls/grep/read/inspect 文档
  -> agent 用过程 model_message + inline evidence link 流式说明阅读发现
  -> 最终 model_message 正文直接回答，并在被支撑句子后紧跟数字 evidence citation
  -> backend 持久化事件并转发给前端
```

## 2. 与 Backend 的关系

典型交互链路是：

```text
backend 读取上传 PDF/DOCX bytes
  -> PDF 调用 POST /v1/document-processor/process
  -> DOCX 调用 POST /v1/document-processor/docx/process
  -> 拿到 filename + html + display_html + markdown + blocks
  -> backend 保存 task documents、messages 和事件游标
  -> 用户每次提问时，backend 生成 completion_id
  -> 调用 POST /v1/document-qa/chat/completions
       body = documents(filename + html) + OpenAI 风格 append-only messages + run_options
  -> agent 返回 text/event-stream
       completion.created
       source_indexed
       model_message / tool_started / tool_completed / tool_failed
       completion.completed / completion.cancelled / completion.failed
  -> backend 入库、转发给前端，并更新下一轮 append-only messages
```

`agent service` 不负责：

- 前端任务创建、任务列表和断线续传。
- 多轮 messages 的长期保存。
- 用户上传文件的持久化。
- replay HTML 的最终组装。
- cancel 后的前端连接管理；它只提供 completion 级取消信号。

## 3. 当前结构

```text
agent/
├── main.py
├── routes/
│   ├── document_processor.py
│   └── file_extraction_agent.py
├── docs/
│   ├── API.md
│   ├── DESIGN.md
│   └── DEVLOG.md
└── service/
    ├── document_processor/
    │   ├── processor.py
    │   ├── schemas.py
    │   └── docs/
    │       ├── API.md
    │       └── DESIGN.md
    └── file_extraction_agent/
        ├── processor.py
        ├── schemas.py
        ├── input_adapter.py
        ├── impl/
        │   ├── graph.py
        │   ├── html_index.py
        │   ├── html_state.py
        │   ├── html_tools.py
        │   ├── model_factory.py
        │   └── resolution_new.py
        └── docs/
            └── DESIGN.md
```

`routes/` 只做 HTTP 协议适配，真实实现统一放在 `service/` 包内。

## 4. 模块边界

### `document_processor`

输入是可读的 PDF 或 DOCX 文件对象。PDF 由 `processor.process(...)` 调
MinerU；DOCX 由 `docx_processor.process_docx(...)` 调 `python-docx`。

```text
PDF UploadFile / file-like object
  -> 校验 file_obj.read() 是否可调用
  -> 校验或推断 PDF 类型
  -> 调用 MinerU 解析 PDF bytes
  -> 生成语义 HTML、展示 HTML、markdown、md_list 和 blocks
  -> 返回 ProcessResult(filename, html, display_html, markdown, md_list, blocks, meta_info, warnings)
```

```text
DOCX UploadFile / file-like object
  -> 校验 file_obj.read() 是否可调用
  -> python-docx 解析 DOCX bytes
  -> 按 Word body 原始顺序读取 paragraph/table
  -> 只用 Word heading style 建 section；无 heading style 时保持 flat blocks
  -> 生成语义 HTML、展示 HTML、markdown、md_list 和 blocks
  -> 返回 ProcessResult(filename, html, display_html, markdown, md_list, blocks, meta_info, warnings)
```

失败语义：

- 文件不可读、PDF 文件类型不是 PDF 或无法确认 PDF 时返回 422。
- MinerU 或解析运行时失败时，错误向上抛给路由层。

### `file_extraction_agent`

输入是 backend 每轮提供的 `completion_id + documents + messages + run_options`。

```text
POST /v1/document-qa/chat/completions
  -> route 解析 ChatCompletionRequest
  -> processor.create_completion_stream(...)
  -> input_adapter 校验 completion_id/documents/messages/run_options
  -> html_index 把多份 HTML 构建成只读 virtual document repository
  -> graph 输出 completion.created 和 source_indexed
  -> resolution_new 让模型通过 ls / grep / read / inspect 浏览文档
  -> html_tools 把每次工具调用写成 tool_started/tool_completed/tool_failed
  -> 过程 model_message 在阅读过程中内嵌 evidence:// Markdown link
  -> 最终 model_message 带 is_final=true，在被支撑句子后紧跟数字 evidence citation
  -> completion.completed / completion.cancelled / completion.failed 收口 SSE
```

`file_extraction_agent` 第一版只在内存 `_ACTIVE_COMPLETIONS` 保存 active runtime，用于取消正在运行的 completion。它不保存历史 completion，也不支持多 worker 进程共享 cancel 状态。

## 5. 主链路

```text
raw PDF/DOCX
  -> document_processor
  -> backend 持久化 documents + display_html
  -> 用户提问
  -> backend 调用 document QA chat completion
  -> agent stream 输出阅读过程、工具调用和句尾数字 citation 的最终回答
  -> backend 保存 events/messages
  -> 下一轮用户提问时 backend 再传入更新后的 append-only messages
```

## 6. HTTP 入口

当前对外保留这些路径：

```text
GET  /healthz
POST /v1/document-processor/process
POST /v1/document-processor/docx/process
POST /v1/ocr/process
POST /v1/document-qa/chat/completions
GET  /v1/document-qa/chat/completions/{completion_id}
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

`/v1/ocr/process` 只是 PDF `document_processor` 的兼容旧路径。旧字段抽取路径 `/v1/file-extraction-agent/extract/stream` 在本分支已删除。

## 7. 运行时环境

常见环境变量：

- `BASE_URL`
- `OPENAI_API_KEY`
- `MODEL`
- `MODEL_API_TRANSPORT`：只支持 `responses` 或 `chat_completions`，默认 `responses`
- `TEMPERATURE`
- `TOP_P`
- `TOP_K`
- `REASONING_EFFORT`
- `MODEL_MAX_RETRIES`
- `MODEL_REQUEST_TIMEOUT`
- `MINERU_BIN`
- `DOCUMENT_PROCESSOR_MINERU_LANG`

`document_processor` 使用 MinerU 相关变量；`file_extraction_agent` 使用模型连接变量。

## 8. 当前约束

- `document_processor` 只处理 PDF 和 DOCX，不支持 legacy `.doc`。
- `file_extraction_agent` 只处理 backend 预先整理好的 `documents(filename + html)`，不负责读取上传文件。
- `file_extraction_agent` 接收的 `messages` 采用 OpenAI chat 结构；backend 会把上一轮 assistant 的 `tool_calls` 和对应 `tool` 结果一起重建回来。
- QA completion 当前总是以 SSE 返回；非流式 chat completion 还没有实现。
- `GET /v1/document-qa/chat/completions/{completion_id}` 当前是占位调试接口。
- cancellation 是本地 completion 级取消：SSE consumer 检查 cancel flag 后立即输出 `completion.cancelled` 并关闭响应；producer 若仍阻塞在 provider stream，会依赖有限 request timeout 回收，迟到事件会被丢弃。
- 第一版要求单进程/单 worker 部署；多 uvicorn worker 会让内存 `_ACTIVE_COMPLETIONS` 不共享，导致 cancel 可能找不到目标 completion。
