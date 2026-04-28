# File Extraction Agent

`service.file_extraction_agent` 负责在 **backend 已按 session 聚合好的标准化 blocks** 上做字段抽取，并返回可审计、可治理的 `ExtractionResult`。它不解析原始 `pdf/docx`，不写数据库，也不决定结果是否允许入库；这些职责分别属于 `service.document_processor`、`backend` 和后续治理层。

这个包的核心价值不是“全文一次性转 JSON”，而是把字段抽取拆成可追踪的证据预选、字段定案、工具补查和规则后处理。

## 主处理链路

当前统一入口是 `processor.extract(...)`：

```text
backend 聚合后的 blocks + 显式 task_spec
  -> processor.extract(...)
  -> input_adapter.build_graph_input(...) 校验 block_id 必填且唯一，并组装内部 ExtractionInput
  -> broad_extraction.py 为每个字段预选相关 blocks 和 evidence
  -> resolution.py 逐字段调用模型做最终定案
  -> resolution.py 按模型请求调用 get_field_bundle(...) 或 lookup_blocks_for_field(...)
  -> validation.py::apply_validation_rules(...) 执行 validation_rules 后处理
  -> validation.py::apply_field_constraints(...) 按 FieldDefinition 做 required / enum_values / type 约束校验
  -> graph.py 把内部 FieldDecision[] 映射成对外 ExtractionResult
```

如果 broad 或 resolution 中途失败，`graph.py` 会统一返回 `status="failed"` 的 `ExtractionResult`，并在 trace 中记录失败阶段、错误类型、错误信息和失败前已有的字段证据。

## 职责边界

适合交给这个包处理的输入：

- 已经标准化成 `NormalizedBlock[]`
- 已经补齐 `document_id`、文本、页码、可选 bbox 和稳定唯一的 `block_id`
- 已经明确本次抽取任务的 `TaskSpec`
- 需要返回字段级 `result` 和字段级 `trace`

不要把下面这些职责放进这个包：

- 原始文件解析、OCR 或 Markdown 标准化
- backend session 聚合和文件下载
- route policy、人工复核流转或写库判断
- 直接访问 backend 数据库或底层 storage

## 快速使用

在 `agent/` 目录安装依赖：

```bash
conda activate agent-gate
cd ./agent
pip install -e ".[dev]"
```

最小调用示例：

```python
from service.file_extraction_agent.processor import extract
from service.file_extraction_agent.schemas import FieldDefinition, NormalizedBlock, TaskSpec


blocks = [
    NormalizedBlock(
        document_id="doc-1",
        block_id="doc-1:p1:b1",
        page_no=1,
        text="发票号码：INV-001",
    )
]

task_spec = TaskSpec(
    task_name="invoice",
    fields=[
        FieldDefinition(
            field_name="invoice_no",
            display_name="发票号",
            type="string",
            required=True,
        )
    ],
)

result = extract(
    blocks=blocks,
    task_spec=task_spec,
    base_url="https://llm.example.com/v1",
    openai_api_key="your-api-key",
    model="gpt-compatible-model",
)

print(result.status)
print(result.result.fields[0].value)
print(result.trace.fields[0].evidence.block_ids)
```

测试里通常直接传 `extractor_client`，用 fake client 绕过真实模型调用。

## 输入契约

### `blocks`

`blocks` 是主输入，类型是 `list[NormalizedBlock]`。每个 block 至少需要：

- `document_id`：文档 id
- `block_id`：backend 或 session 聚合层生成的稳定唯一 block id；缺失或重复会被拒绝
- `text`：标准化后的块文本

常用可选字段：

- `page_no`：页码
- `bbox`：标准化坐标框
- `kind`：块类型，默认是 `text`
- `meta_info`：上游保留的额外元信息

### `task_spec`

`task_spec` 定义本次要抽取哪些字段。每个字段至少包含：

- `field_name`
- `display_name`
- `type`

当前支持的字段类型：

- `string`
- `date`
- `enum`
- `money`
- `boolean`

字段还可以声明：

- `required` / `critical` / `allow_missing`
- `validation_rules`
- `cross_field_hints`
- `lookup_hints`
- `enum_values`

调用方必须直接传 `TaskSpec`。`service.file_extraction_agent` 当前不维护本地 `task_specs/` 目录，也不再支持 `task_spec_name` 加载；schema 选择应由 backend 或调用方在进入本包前完成。

## validation_rules

`validation_rules` 和基础字段约束由 `impl/validation.py` 统一后处理：

```text
模型返回 FieldResolutionDecision
  -> resolution.py 按 used_block_ids 绑定 FieldEvidence
  -> resolution.py 组装 FieldDecision
  -> validation.py::apply_validation_rules(...) 读取字段 validation_rules
  -> 如有规则，执行通用校验、覆盖或跨字段一致性收口
  -> validation.py::apply_field_constraints(...) 检查基础字段约束
  -> 返回最终 FieldDecision
```

当前支持两类通用规则：

- `source_type=table_rows`：按 `columns`、`filter`、`exclude`、`target_column` 从标准化表格行筛选最小证据片段，并可覆盖模型混入的无关行。
- `operation=count_items`：按 `source_field` 的已定案结果计算条目数量，用于保证列表字段和数量字段一致。

规则层只能作为模型定案后的通用约束校验或 trace 补强，不能绕过模型自行决定字段值。每次规则覆盖都应记录 `validation_rule` action，说明访问了哪些证据、应用了什么规则。

`validation_rules` 执行后，系统还会按字段定义做基础约束校验：

```text
FieldDecision
  -> 检查 required / allow_missing
  -> 检查 enum 值是否在 enum_values 中
  -> 检查 money / date / boolean 的基本类型形状
  -> 不满足时把该字段降级为 failed，并记录 field_constraint action
```

## 模型配置

如果没有显式传入 `extractor_client`，`extract(...)` 会调用 `build_extractor_client(...)` 创建模型客户端。

连接信息解析顺序：

```text
extract(...) 显式参数
  -> 环境变量 BASE_URL / OPENAI_API_KEY / MODEL
  -> MODEL 仍为空时使用代码内默认模型
```

必需配置：

- `base_url` 或 `BASE_URL`
- `openai_api_key` 或 `OPENAI_API_KEY`

可选配置：

- `model` 或 `MODEL`
- `structured_output_strategy`：`auto`、`json_schema` 或 `tool_call`

`structured_output_strategy="auto"` 时会先尝试 `json_schema`，不支持时再回退到 `tool_call`。

## 运行选项

`run_options` 使用公开契约 `schemas.py::RunOptions`，HTTP 入口、Python 入口和
内部 graph 共用这一份运行配置：

- `allow_extra_lookup`：是否允许 resolution 模型请求全局补查
- `max_lookup_calls_per_field`：每个字段最多允许几次补查
- `lookup_top_k`：每次补查最多返回几个 blocks
- `max_prompt_blocks`：broad prompt 最多携带的 blocks 数
- `max_prompt_block_chars`：broad prompt 单个 block 文本最多保留的字符数
- `max_resolution_evidence_fields`：resolution prompt 最多携带的字段 evidence 数，目标字段优先保留
- `max_prompt_evidence_text_chars`：resolution prompt 单条 evidence 文本最多保留的字符数
- `keep_detailed_trace`：预留的详细 trace 开关

Python 入口和 HTTP `/v1/file-extraction-agent/extract` 都支持传入 `run_options`。

## 输出结构

`extract(...)` 返回 `ExtractionResult`：

```text
ExtractionResult
  -> status: completed / failed
  -> failure_reason
  -> result.fields[]
       -> field_name
       -> status: resolved / failed
       -> value
  -> trace.fields[]
       -> field_name
       -> evidence
       -> related_fields
       -> actions
       -> reason / failure_reason
  -> trace.warnings
  -> trace.metadata
```

`result.fields[]` 只放最终业务结果；`trace.fields[]` 保存证据、相关字段、工具动作、规则动作和失败原因。外层治理层应结合 `result` 和 `trace` 决定后续通过、转人工、拒绝还是 fallback。

## 目录结构

```text
service/file_extraction_agent/
├── processor.py          # 对外统一入口
├── input_adapter.py      # 外部输入到内部 ExtractionInput 的适配层
├── schemas.py            # 对外稳定输入输出契约
├── extractor_client.py   # 结构化模型客户端构造与调用
├── impl/
│   ├── schemas.py        # 内部流程对象
│   ├── graph.py          # broad -> resolution 的编排和失败收口
│   ├── block_ids.py      # block id 必填和唯一性校验
│   ├── broad_extraction.py
│   ├── resolution.py     # 字段定案和工具调度
│   ├── validation.py     # validation_rules 和基础字段约束后处理
│   ├── tools.py
│   ├── prompts.py
│   └── state.py
└── docs/
    ├── API.md
    ├── DESIGN.md
    └── DEVLOG.md
```

调用方接口见 [`docs/API.md`](docs/API.md)，更完整的设计边界和实现细节见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 测试

在 `agent/` 目录执行：

```bash
conda activate agent-gate
pytest tests/file_extraction_agent
```

测试说明文档放在 `agent/tests/file_extraction_agent/docs/`，每个测试文件对应一份同名说明文档，例如：

```text
test_processor.py -> docs/test_processor.md
test_resolution.py -> docs/test_resolution.md
test_tools.py -> docs/test_tools.md
```
