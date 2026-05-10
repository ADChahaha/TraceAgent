# Agent Service

`agent/` 是 TraceAgent 的 AI 能力层，给 `backend` 提供三个 HTTP 阶段：

- `document_processor`：把 PDF 标准化成抽取友好的 HTML、展示用 HTML、markdown、blocks 和处理元信息。
- `file_extraction_agent`：在标准化 HTML 上按外部 `task_spec` 做字段抽取，并返回 `result + trace`。
- `route_policy_agent`：根据字段输出、证据文本和抽取过程摘要判断字段级 `accept / review / reject`。

它不访问 backend SQLite，不保存任务状态，不执行人工复核，也不写最终结果。任务、review、audit 和字段提交都由 `backend` 负责。

## 基本链路

```text
backend 上传 PDF bytes
  -> POST /v1/document-processor/process
  -> document_processor 返回 html / display_html / markdown / md_list / blocks
  -> backend 保存文档结构，并在多文档任务中聚合 html
  -> POST /v1/file-extraction-agent/extract
  -> file_extraction_agent 返回 ExtractionResult(result + trace)
  -> backend 从 result、trace refs 和 trace actions 组装 route policy 输入
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
POST /v1/file-extraction-agent/extract
```

接收 backend 聚合后的 `html`、外部 `task_spec`、可选 `run_options` 和可选模型覆盖配置。

```text
html + task_spec
  -> input_adapter 校验 html、task_spec.fields 和 run_options
  -> html_index 构建 document tree、element/table/row 索引
  -> resolution_new 按 compact outline 调用 Reading Stages / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / set_field / finish
  -> graph 汇总字段结果、reading_stages、document_tree、field_states 和 actions
  -> 返回 ExtractionResult(result + trace)
```

### 抽取工具和 trace 粒度

`file_extraction_agent` 的 replay 粒度来自工具调用本身。每次工具调用都会写入 `trace.actions`，backend 再把这些动作和证据 id 组装给前端。

| Tool | 阶段 | trace 粒度 | trace 里保留的关键信息 | 用途 |
| --- | --- | --- | --- | --- |
| `start_stage(title, focus, basis)` | resolution | 阅读阶段级 | 阶段标题、关注内容、进入阶段的理由 | 让右侧 replay 知道当前围绕什么理解目标读文档；当前 stage 完成前不能开启新 stage。 |
| `append_stage_progress(stage_id, type, summary)` | resolution | 阶段进展级 | `investigate/compare/verify_absence/conclude` 和摘要 | 展示阶段内“看了什么、如何比较多处证据、如何确认缺失、得出什么”。 |
| `record_stage_evidence(stage_id, evidence_ids, observation, supports, limits)` | resolution | 候选证据级 | 精确证据 id、观察、支持点和限制 | 记录可能复用的关键依据，但不替代最终字段证据。 |
| `review_stage_evidence(stage_id)` | resolution | 候选证据复看级 | 按记录顺序返回 notes | 帮模型在较长阶段里复看已记录依据。 |
| `complete_stage(stage_id, finding)` | resolution | 阶段结论级 | 阶段 finding | 标记一个阅读阶段已形成稳定理解，不额外追加 `conclude` progress。 |
| `read_section(section_id)` | resolution | 章节预览级 | `section_id` 和真实后代 block previews | 从 heading id 读取真实后代预览，不吞并平级段落/列表/表格。 |
| `read_blocks(section_id, indexes)` | resolution | 精确块读取级 | scope id、离散 indexes、block HTML/ref、evidence ids | 精确追踪模型看了哪些文本块、列表 ref 或表格 ref。 |
| `read_block_range(section_id, start_index, count)` | resolution | 连续块读取级 | scope id、连续窗口、实际 indexes、evidence ids | 顺序补上下文。 |
| `read_list(section_id, block_offset, item_offset, number)` | resolution | 列表项读取级 | list id、item ids、item 文本 | 追踪列表字段来自哪些 `li`。 |
| `query_table(section_id, block_offset, sql)` | resolution | 表格查询级 | 表格 id、SQL、行证据、`table_audit`、summary | 追踪表格字段来自哪张表、哪些行，以及表格空值事实观察。 |
| `preview_inline_evidence(source_id, start_index, count)` | resolution | 文本 inline 证据级 | inline id、文本和字符范围 | 把整段文本细化为最终可引用证据。 |
| `set_field(name, value, evidence_ids, status, failure_reason, stage_id, rationale)` | resolution | 字段写入级 | 字段名、字段值、状态、证据 id、字段级 rationale | 追踪字段最终为什么被写入或为什么失败；字段和候选证据 note 通过同一组 `evidence_ids` 关联。 |
| `finish()` | resolution | 运行校验级 | 完成状态和错误列表 | 追踪本轮抽取是否真正完成，或卡在哪些字段/证据校验上。 |

这套工具让前端可以把抽取过程回放成：

```text
阅读阶段
  -> 读取章节、文本块、列表或表格
  -> 记录候选证据
  -> 写入字段和字段级 rationale
  -> 完成抽取校验
```

```text
POST /v1/route-policy-agent/evaluate
```

接收 `task_spec`、`field_outputs`、`refs_with_text`、`field_processes` 和可选模型覆盖配置。

```text
task_spec + field_outputs + refs_with_text + field_processes
  -> input_validator 校验字段名、字段输出、证据文本和过程摘要
  -> mapper 合并字段定义、字段值、证据文本和抽取过程摘要
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
