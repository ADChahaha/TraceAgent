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
  -> resolution_new 按字段和 outline 调用 update_soft_plan / overview / read_section / read_blocks / read_block_range / read_list / query_table / preview_inline_evidence / set_field / finish
  -> graph 汇总字段结果、soft_plan、document_tree、plan_statuses、field_states 和 actions
  -> 返回 ExtractionResult(result + trace)
```

### 抽取工具和 trace 粒度

`file_extraction_agent` 的 replay 粒度来自工具调用本身。每次工具调用都会写入 `trace.actions`，backend 再把这些动作和证据 id 组装给前端。

| Tool | 阶段 | trace 粒度 | trace 里保留的关键信息 | 用途 |
| --- | --- | --- | --- | --- |
| `update_soft_plan(plan)` | resolution | 软计划级 | `step/status/plan_index` | 同步右侧 plan 进度，说明当前在执行哪一组局部证据阅读。 |
| `read_element(element_id, reason)` | resolution | 单个 HTML 元素级 | `element_id`、读取理由、元素 HTML 摘要、evidence id | 只读取一个指定 id 的小元素，例如一个标题、一个段落、一个列表项，或一张表的结构摘要；适合精确追踪“模型看了哪一块”。 |
| `read_section(section_id, reason, depth)` | resolution | 文件树递归章节级 | `section_id`、`depth`、读取理由、递归读到的 evidence ids | 从一个 heading id 开始，沿文档顺序读取该标题下的内容；遇到同级或更高级标题停止，`depth` 控制读到几层子标题；适合追踪“模型读了哪一段章节范围”。 |
| `table_extraction(table_id, sql, reason)` | resolution | 表格查询级 | 表格 id、SQL、行证据、`table_audit`、`query_audit` | 追踪表格字段来自哪张表、哪些行，以及表格质量观察。 |
| `paragraph_extraction(element_id, pattern, reason)` | resolution | 文本匹配级 | 元素 id、正则、匹配文本、span、evidence id | 追踪字段值在文本块里的具体匹配位置。 |
| `set_field(name, value, evidence_ids, reason, status, failure_reason)` | resolution | 字段写入级 | 字段名、字段值、状态、证据 id、写入原因或失败原因 | 追踪字段最终为什么被写入或为什么失败。 |
| `finish()` | resolution | 运行校验级 | 完成状态和错误列表 | 追踪本轮抽取是否真正完成，或卡在哪些字段/证据校验上。 |

这套工具让前端可以把抽取过程回放成：

```text
计划
  -> 标记当前计划步骤
  -> 读取元素或章节
  -> 查询表格或匹配文本
  -> 写入字段和证据
  -> 完成抽取校验
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
