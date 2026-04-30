# File Extraction Agent

`service.file_extraction_agent` 负责在 **backend 已按 session 聚合好的标准化 blocks** 上做字段抽取，并返回可审计、可治理的 `ExtractionResult`。它不解析原始 `pdf/docx`，不写数据库，也不决定结果是否允许入库；这些职责分别属于 `service.document_processor`、`backend` 和后续治理层。

这个包的核心价值不是“全文一次性转 JSON”，而是把字段抽取拆成可追踪的候选召回、字段定案和工具动作。

## 为什么不用纯抽取

纯抽取通常把全文或长 markdown 一次性交给模型，让模型直接输出 JSON。遇到长表格、多行名单和反复出现的业务词时，模型容易被标题、正文总数或大量相似行干扰。当前 agent 链路把判断拆成下面几步：

```text
标准化 blocks + task_spec
  -> search_grep 同时检索正文段落和表格行，query 统一使用 `term1 OR term2 OR term3`
  -> broad 只把可能支撑字段的 ref 写入候选池，不直接给最终值
  -> resolution 从候选池读取证据，必要时二次 search_grep 补证
  -> final_decision 必须引用 candidate_id
  -> graph 用 candidate_id 回查 ref、block_id、document_id、page_no 和文本
  -> result 保存最终业务值，trace 保存证据和动作链路
```

因此像“只统计作品类型为学术论文的论文题目”这类任务，不会只因为正文写了“111位学生”或每行都有“论文替代”就把总人数或全表题目误当答案。

## 主处理链路

当前统一入口是 `processor.extract(...)`：

```text
backend 聚合后的 blocks + 显式 task_spec
  -> processor.extract(...)
  -> input_adapter.build_graph_input(...) 调用 block_contract 校验 blocks，并组装内部 ExtractionInput
  -> graph.py 创建 GraphState 和 paragraph/table row 索引
  -> broad.runner 按字段调用 search_grep / add_broad_candidate / finish_broad
  -> resolution.runner 基于候选池调用 get_candidate_bundle / search_grep / add_resolution_candidate / final_decision
  -> graph.py 用 candidate_id -> ref -> index 回查证据
  -> 返回 ExtractionResult(result + trace)
```

如果 broad 或 resolution 中途失败，`graph.py` 会统一返回 `status="failed"` 的 `ExtractionResult`，并在 trace 中记录失败阶段、错误类型、错误信息和失败前已有的字段证据。
`search_grep` 每次同时搜索正文段落和表格行，多关键词 query 固定写成 `term1 OR term2 OR term3`。

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
- `list`：字符串列表，多值字段必须返回数组而不是分隔符字符串。

字段还可以声明：

- `required` / `critical` / `allow_missing`
- `validation_rules`
- `cross_field_hints`
- `lookup_hints`
- `enum_values`

调用方必须直接传 `TaskSpec`。`service.file_extraction_agent` 当前不维护本地 `task_specs/` 目录，也不再支持 `task_spec_name` 加载；schema 选择应由 backend 或调用方在进入本包前完成。

## 字段提示和候选证据

`validation_rules`、`lookup_hints` 和 `cross_field_hints` 仍属于 `FieldDefinition` 的稳定字段，当前实现会把它们作为模型可见的字段上下文保留。系统不再维护独立规则后处理阶段，也不会用规则绕过模型自行覆盖字段值。

当前字段定案必须遵循下面的候选链路：

```text
grep 返回 ref
  -> add_broad_candidate / add_resolution_candidate 生成 candidate_id
  -> final_decision 只能引用 candidate_id
  -> graph 用 candidate_id 回查 ref、document_id、page_no 和 block_id
  -> trace.evidence
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
- `broad_model`：只覆盖 broad 候选召回阶段
- `resolution_model`：只覆盖 resolution 字段定案阶段
- `structured_output_strategy`：固定只支持 `tool_call`，未传时默认也是 `tool_call`

`tool_call` 会在客户端内部映射到 LangChain 的 `function_calling`。显式传入 `json_schema` 或 `auto` 会被拒绝，不再保留协议回退。

## 运行选项

`run_options` 使用公开契约 `schemas.py::RunOptions`，HTTP 入口、Python 入口和
内部 graph 共用这一份运行配置：

- `max_prompt_blocks`：broad prompt 最多携带的 blocks 数
- `max_prompt_block_chars`：broad prompt 单个 block 文本最多保留的字符数
- `max_resolution_candidates`：resolution prompt 最多携带的候选证据数
- `max_broad_iterations`：单字段 broad loop 最大动作轮次
- `max_resolution_iterations`：单字段 resolution loop 最大动作轮次
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

返回边界固定为：

- `result.fields[]` 只放字段最终业务结果，适合直接进入后续业务表单或展示层。
- `trace.fields[]` 保存候选证据、相关字段、工具动作、定案原因和失败原因，适合审计、前端高亮、route policy 和人工复核。
- `result` 不重复塞证据文本；需要解释“为什么是这个值”时读 `trace`。

外层治理层应结合 `result` 和 `trace` 决定后续通过、转人工、拒绝还是 fallback。

## 目录结构

```text
service/file_extraction_agent/
├── processor.py          # 对外统一入口
├── input_adapter.py      # 外部输入到内部 ExtractionInput 的适配层
├── schemas.py            # 对外稳定输入输出契约
├── extractor_client.py   # 结构化模型客户端构造与调用
├── block_contract.py     # blocks 入口契约校验
├── impl/
│   ├── schemas.py        # 内部流程对象
│   ├── graph.py          # broad -> resolution 的编排和失败收口
│   ├── state.py          # 内部索引和运行态
│   ├── broad/            # broad runner 和 prompts
│   ├── resolution/       # resolution runner 和 prompts
│   └── tools/            # search 和 candidates
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
