# Agent Service

`agent/` 是 TraceAgent 的 AI 能力层，给 `backend` 提供三个 HTTP 阶段：

- `document_processor`：把 PDF 标准化成抽取友好的 HTML、展示用 HTML、markdown、blocks 和处理元信息。
- `file_extraction_agent`：在多个语义 HTML 文档上按外部 `task_spec` 做字段抽取，并用 NDJSON stream 返回工具事件、字段写入和最终结果。
- `route_policy_agent`：根据字段输出、证据文本和抽取过程摘要判断字段级 `accept / review / reject`。

它不访问 backend SQLite，不保存任务状态，不执行人工复核，也不写最终结果。任务、review、audit 和字段提交都由 `backend` 负责。

## 基本链路

```text
backend 上传 PDF bytes
  -> POST /v1/document-processor/process
  -> document_processor 返回 html / display_html / markdown / md_list / blocks
  -> backend 保存文档结构，并把多文档整理为 documents(filename + html)
  -> POST /v1/file-extraction-agent/extract/stream
  -> file_extraction_agent 流式返回工具事件和 result_completed
  -> backend 从 result_completed、evidence selector 和工具事件组装 route policy 输入
  -> POST /v1/route-policy-agent/evaluate
  -> route_policy_agent 返回字段级 route 决策
  -> backend 继续驱动 review / final result / audit
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
export ROUTE_POLICY_MODEL="your-route-policy-model"
export MINERU_BIN="mineru"
export DOCUMENT_PROCESSOR_MINERU_LANG="japan"
```

中文 PDF 可以把 `DOCUMENT_PROCESSOR_MINERU_LANG` 设为 `ch`。

启动服务时建议使用根 README 约定的 `8001` 端口，避免和 backend 的 `8000` 冲突：

```bash
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

启动后可访问：

- `GET /healthz`
- `GET /docs`

## HTTP 入口

```text
POST /v1/document-processor/process
POST /v1/ocr/process
```

接收 multipart PDF 文件。`/v1/ocr/process` 是兼容旧路径的同义入口。

```text
UploadFile
  -> route 层包装成可读 file-like 对象
  -> service.document_processor.processor.process(file_obj, file_type)
  -> 校验 PDF 类型和 file_obj.read()
  -> MinerU 解析 PDF bytes
  -> mineru_html 生成 html / display_html / markdown / md_list / blocks
  -> 返回 ProcessResult
```

```text
POST /v1/file-extraction-agent/extract/stream
```

接收 backend 准备好的 `documents(filename + html)`、外部 `task_spec`、可选 `run_options` 和可选模型覆盖配置，返回 `application/x-ndjson`。

```text
documents + task_spec
  -> input_adapter 校验 documents、task_spec.fields 和 run_options
  -> html_index 构建 /001-filename-title/... 只读虚拟文件树
  -> resolution_new 按字段调用 tree / read / add_candidate_evidence / review_evidences / write_field / submit_result
  -> graph 逐行输出 tool_started / tool_completed / tool_failed / field_written / result_completed
```

### 抽取工具和 stream 粒度

`file_extraction_agent` 的可解释性来自真实工具调用、用户可见 `reason` 和可反查 evidence selector。agent 不直接连接前端，也不写 DB；backend 后续负责消费 NDJSON、入库和转发。

| Tool / Event | 粒度 | 保留的关键信息 | 用途 |
| --- | --- | --- | --- |
| `tree(path_id, depth)` | 文件树导航 | `evidence://` locator、展开深度、目录/文件名 | 追踪模型先看了哪些文档和章节。 |
| `read(path_id)` | 文件读取 | `.md/.list/.table` locator、Markdown 阅读视图 | 追踪模型读了哪个 paragraph、list 或 table 文件。 |
| `add_candidate_evidence(field_id, path_id)` | 候选证据记录 | 字段 id、一个 block 级 `evidence://` locator | 追踪模型看到哪些对象可能支持、反驳或限定字段。 |
| `review_evidences(field_id)` | 候选证据复看 | 字段描述、当前值、候选 block、展开后的 inline selector 和反查文本 | 帮助模型像看笔记一样筛选最终证据。 |
| `write_field(field_id, value, final_evidence, status)` | 字段写入 | 字段 id、值、最终 inline selector、状态、可见说明 | 追踪字段最终为什么被写入或标记缺失。 |
| `submit_result()` | 结果校验 | 当前字段缓冲、校验结果或错误 | 追踪本轮抽取是否通过 schema 和证据校验。 |
| `result_completed` | 最终收口 | `fields[]`、trace、失败原因 | 给 backend 一个完整可入库的最终事件。 |

这套工具让前端可以把抽取过程回放成：

```text
展开目录
  -> 读取 paragraph/list/table
  -> 记录可能相关的候选 block evidence
  -> 复看字段候选并展开 inline evidence
  -> 写入字段值和 final_evidence
  -> 提交并校验结果
```

```text
POST /v1/route-policy-agent/evaluate
```

接收 `task_spec`、`field_outputs`、`refs_with_text`、`field_processes` 和可选模型覆盖配置。

```text
task_spec + field_outputs + refs_with_text + field_processes
  -> input_validator 校验字段名、字段输出、证据文本和过程摘要
  -> mapper 合并字段定义、字段值、证据文本和 resolution 过程摘要
  -> 确定性缺失或失败先直接 review
  -> query_audit/table_audit 作为事实观察进入 route policy prompt
  -> route policy LLM 通过 tool_call 输出字段级 route
  -> 返回 RoutePolicyResult(field_routes)
```

route policy 不重新抽取字段，不读取完整原文、工具返回正文、表格原始行、cell 值或 action refs，只消费 backend 组装好的证据文本和过程摘要。更细的输入契约见 [docs/API.md](docs/API.md)。

## 目录结构

```text
agent/
  main.py
  routes/
    document_processor.py
    file_extraction_agent.py
    route_policy_agent.py
  service/
    document_processor/
    file_extraction_agent/
    route_policy_agent/
  tests/
  docs/
```

模块边界：

- `main.py` 只创建 FastAPI app 并挂载 routers。
- `routes/` 只做 HTTP 协议适配和错误状态映射。
- `service/document_processor/` 放 PDF 标准化实现。
- `service/file_extraction_agent/` 放字段抽取 graph、工具和 schema。
- `service/route_policy_agent/` 放 route policy 输入校验、prompt 映射和模型调用。

## 参考文档

- [docs/API.md](docs/API.md)：HTTP API 和请求/响应契约。
- [docs/DESIGN.md](docs/DESIGN.md)：agent 服务模块边界和主链路。
- [service/document_processor/docs/DESIGN.md](service/document_processor/docs/DESIGN.md)：PDF 标准化设计。
- [service/file_extraction_agent/docs/DESIGN.md](service/file_extraction_agent/docs/DESIGN.md)：字段抽取设计。
- [service/route_policy_agent/docs/DESIGN.md](service/route_policy_agent/docs/DESIGN.md)：route policy 设计。
