# Agent Service Design

这份文档描述 `agent service` 当前只保留的两个阶段：`document_processor` 和 `file_extraction_agent`。它的职责很窄，只负责把上传文件标准化成可读文档，再把这些文档交给抽取器产出字段结果和 trace；任务状态、字段提交、审计和任何人工审核都由 `backend` 处理。

## 目标

`agent/` 的目标是把“原始文件处理”和“字段抽取”拆开，避免一个模块同时承担文件解析、模型抽取、结果拼装和持久化。

## 与 Backend 的关系

`agent service` 不直接访问 `backend` 的 SQLite，也不保存任务状态。

典型交互链路是：

```text
backend 读取上传 PDF bytes
  -> 调用 document_processor
  -> 拿到 filename + html / display_html / markdown / blocks
  -> 组织 documents(filename + html)
  -> 调用 file_extraction_agent
  -> 拿到 result_completed(fields + trace)
  -> backend 直接提交 resolved 字段，failed/None 字段保持未提交
  -> backend 写入最终结果和 audit
```

也就是说，`agent service` 只负责文档标准化和字段抽取，不负责任务治理、字段提交、审计或人工审核。

## 当前结构

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
            ├── API.md
            └── DESIGN.md
```

`agent/pyproject.toml` 负责打包 `routes/` 和 `service/`。`routes/` 只做 HTTP 协议适配，真实实现统一放在 `service` 包内，并通过 `service.document_processor` 和 `service.file_extraction_agent` 访问。

## 模块边界

### `document_processor`

- 输入是可读的 PDF 文件对象和可选 `file_type`
- 先校验文件对象和文件类型，再交给 MinerU 解析
- 输出 `ProcessResult(filename + html + display_html + markdown + md_list + blocks + meta_info + warnings)`
- 提供 Python 入口 `service.document_processor.processor.process(...)`
- 提供 HTTP 入口 `routes/document_processor.py`

处理链路：

```text
UploadFile / file-like object
  -> 校验可读性和 PDF 类型
  -> 调用 MinerU 解析 PDF bytes
  -> 生成语义 HTML、展示 HTML、markdown 和 blocks
  -> 返回 ProcessResult
```

失败时：

- 文件不可读、文件类型不是 PDF 或无法确认 PDF 时返回 422
- 解析运行时失败时，错误向上抛给路由层

### `file_extraction_agent`

- 输入是 `documents(filename + html)`、外部 `task_spec` 和可选 `run_options`
- 先由 `input_adapter.py` 校验 documents、task_spec 和运行预算
- 再由 `html_index.py` 把每个 HTML 变成只读虚拟文件树
- 再由 `resolution_new.py` 通过 `tree / read / add_candidate_evidence / review_evidences / write_field / submit_result` 完成字段抽取
- 最后由 `graph.py` 把工具调用序列化成 NDJSON 事件，并用 `result_completed` 收口

处理链路：

```text
documents(filename + html) + task_spec
  -> input_adapter 校验 documents/task_spec/run_options
  -> html_index 构建虚拟文件树、path 索引和 list/table 编号
  -> resolution_new 执行 tree/read/add_candidate_evidence/review_evidences/write_field/submit_result
  -> graph 输出 NDJSON 工具事件
  -> result_completed 返回 fields[] 和 trace
```

这里的 `review_evidences` 只是抽取链路内部的证据复看工具，不是人工审核流程，也不代表 backend 还有单独的 review gate。

## 主链路

```text
raw PDF
  -> document_processor
  -> documents(filename + html)
  -> file_extraction_agent stream
  -> result_completed(fields[] + trace)
  -> backend commit / audit
```

## HTTP 入口

当前对外只保留这几个路径：

- `GET /healthz`
- `POST /v1/document-processor/process`
- `POST /v1/ocr/process`
- `POST /v1/file-extraction-agent/extract/stream`

`/v1/ocr/process` 只是 `document_processor` 的兼容旧路径。

## 运行时环境

`document_processor` 和 `file_extraction_agent` 使用的常见环境变量：

- `BASE_URL`
- `OPENAI_API_KEY`
- `RESOLUTION_MODEL`
- `MINERU_BIN`
- `DOCUMENT_PROCESSOR_MINERU_LANG`

这里只保留文档处理和字段抽取所需模型，不再有额外阶段。

## 当前约束

- `document_processor` 只处理 PDF
- `file_extraction_agent` 只处理 backend 预先整理好的 documents，不负责读取上传文件
- 抽取失败会在 NDJSON 中体现，并由 `result_completed` 或失败事件收口
- 字段提交、任务状态和审计都由 backend 决定
