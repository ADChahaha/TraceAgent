# Agent Service

`agent/` 是 TraceAgent 的 AI 能力层，给 `backend` 提供两个 HTTP 阶段：

- `document_processor`：把 PDF/DOCX 标准化成 QA 友好的语义 HTML、展示用 HTML、markdown、blocks 和处理元信息。
- `file_extraction_agent`：对 backend 传入的多份语义 HTML 做多轮文档 QA chat completion，像 code agent 浏览代码仓库一样用 `tree / grep / read / inspect` 查文档，并通过 SSE 返回带 evidence link 的过程消息和终态事件。

它不访问 backend SQLite，不保存多轮 conversation，也不直接连接前端。任务、append-only messages、事件续传、replay 和最终展示都由 `backend` 负责。

## 基本链路

```text
backend 上传 PDF/DOCX bytes
  -> PDF POST /v1/document-processor/process
  -> DOCX POST /v1/document-processor/docx/process
  -> document_processor 返回 html / display_html / markdown / md_list / blocks
  -> backend 保存文档、对话 messages 和事件游标
  -> 用户提问时 backend 生成 completion_id
  -> POST /v1/document-qa/chat/completions
  -> file_extraction_agent 流式返回 completion.created / source_indexed / model_message / tool_* / completion.*
  -> backend 持久化事件并转发给前端
  -> 下一轮问题由 backend 再次携带 documents + append-only messages 调用 agent
```

## 本地启动

`agent/AGENTS.md` 约定 Python 命令应在 `agent-gate` Conda 环境里执行：

```bash
conda create -n agent-gate python=3.11 -y
conda activate agent-gate
cd /path/to/agent_gate/agent
pip install -e ".[dev]"
```

真实调用模型和 MinerU 时，启动前设置必要变量：

```bash
export BASE_URL="https://your-model-endpoint/v1"
export OPENAI_API_KEY="your-api-key"
export RESOLUTION_MODEL="your-resolution-model"
export MINERU_BIN="mineru"
export DOCUMENT_PROCESSOR_MINERU_LANG="japan"
```

中文 PDF 可以把 `DOCUMENT_PROCESSOR_MINERU_LANG` 设为 `ch`。

启动服务时建议使用根 README 约定的 `8001` 端口，避免和 backend 的 `8000` 冲突：

```bash
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

第一版 QA cancel 依赖单进程内存 `_ACTIVE_COMPLETIONS`，不要使用多个 uvicorn worker。

启动后可访问：

- `GET /healthz`
- `GET /docs`

## HTTP 入口

### 文档标准化

```text
POST /v1/document-processor/process
POST /v1/document-processor/docx/process
POST /v1/ocr/process
```

接收 multipart PDF 或 DOCX 文件。`/v1/ocr/process` 是 PDF 兼容旧路径的同义入口。

```text
PDF UploadFile
  -> route 层包装成可读 file-like 对象
  -> service.document_processor.processor.process(file_obj, file_type)
  -> 校验 PDF 类型和 file_obj.read()
  -> MinerU 解析 PDF bytes
  -> mineru_html 生成 html / display_html / markdown / md_list / blocks
  -> 返回 ProcessResult
```

```text
DOCX UploadFile
  -> route 层包装成可读 file-like 对象
  -> service.document_processor.docx_processor.process_docx(file_obj)
  -> 校验 file_obj.read()
  -> python-docx 解析 DOCX bytes
  -> 按 Word body 原始顺序生成 html / display_html / markdown / md_list / blocks
  -> 返回 ProcessResult
```

### 多文档 QA chat completion

```text
POST /v1/document-qa/chat/completions
GET  /v1/document-qa/chat/completions/{completion_id}
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

`POST /chat/completions` 接收 backend 准备好的 `documents(filename + html)`、多轮 append-only `messages`、可选 `run_options` 和可选模型配置，返回 `text/event-stream`。

```text
completion_id + documents + messages
  -> input_adapter 校验 completion_id、documents、messages 和 max_tool_calls
  -> html_index 构建只读 semantic virtual tree
  -> graph 输出 completion.created + source_indexed
  -> resolution_new 构建 QA prompt 并调用模型
  -> html_tools 提供 tree / grep / read / inspect
  -> model_message 在过程中引用 evidence:// link
  -> graph/processor 输出 completion.completed / completion.cancelled / completion.failed
```

### QA 工具和 stream 粒度

`file_extraction_agent` 的可追溯性来自用户可见 `model_message`、真实工具调用和可反查 evidence selector。agent 不写 DB；backend 负责消费 SSE、入库和转发。

| Tool / Event | 粒度 | 保留的关键信息 | 用途 |
| --- | --- | --- | --- |
| `tree(path_id, depth)` | 文件树导航 | `evidence://` locator、展开深度、目录/文件名 | 追踪模型先看了哪些文档和章节。 |
| `grep(query, scope, kind, max_results)` | 候选搜索 | 命中文档、section、block locator、preview、match_spans | 像 `rg` 一样定位候选 block；不作为最终证据。 |
| `read(locator)` | 上下文读取 | 单个 block 或连续 range 的 Markdown 阅读视图 | 追踪模型实际读了哪些 paragraph/list/table。 |
| `inspect(locator)` | 精确证据展开 | `Sxxx` / `Ixxx` / `Rxxx` inline link 和反查文本 | 支撑具体事实、条件、金额、日期、冲突和最终结论。 |
| `model_message` | 用户可见过程 | 自然语言说明、Markdown evidence link、`is_final`/`stop_signal` | 让用户边看边验证模型阅读过程；backend 用 `is_final=true` 保存最终 assistant 消息。 |
| `completion.completed` | 正常终态 | completion id、status | 本轮 QA 完成并关闭 SSE。 |
| `completion.cancelled` | 取消终态 | completion id、status | backend 调 cancel 后收口本轮流。 |
| `completion.failed` | 失败终态 | completion id、status、error | resolution 失败后收口本轮流。 |

这套工具让前端可以把 QA 过程回放成：

```text
模型说明下一步要查什么
  -> 搜索候选 block
  -> 读取上下文
  -> 展开句子/列表项/表格行证据
  -> 在过程消息或最终回答里引用 evidence link
  -> completion 终态关闭本轮流
```

## 目录结构

```text
agent/
  main.py
  routes/
    document_processor.py
    file_extraction_agent.py
  service/
    document_processor/
    file_extraction_agent/
  tests/
  docs/
```

模块边界：

- `main.py` 只创建 FastAPI app 并挂载 routers。
- `routes/` 只做 HTTP 协议适配和错误状态映射。
- `service/document_processor/` 放 PDF/DOCX 标准化实现。
- `service/file_extraction_agent/` 放文档 QA completion 的 graph、工具、schema 和 active runtime 管理。

## 参考文档

- [docs/API.md](docs/API.md)：HTTP API 和请求/响应契约。
- [docs/DESIGN.md](docs/DESIGN.md)：agent 服务模块边界和主链路。
- [service/document_processor/docs/DESIGN.md](service/document_processor/docs/DESIGN.md)：PDF/DOCX 标准化设计。
- [service/file_extraction_agent/docs/DESIGN.md](service/file_extraction_agent/docs/DESIGN.md)：文档 QA agent 设计。
