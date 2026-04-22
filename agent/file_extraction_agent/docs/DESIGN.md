# File Extraction Agent Design

这份文档面向开发者，说明 `file_extraction_agent` 在 `agent service` 中的代码结构、模块边界和主处理链路。它处理的是 **标准化后的文档 blocks 上的字段级证据预选与字段最终定案**，不负责原始文件解析，也不直接负责写库、外层 route policy 或人工审核流转。

## 目标

`file_extraction_agent` 的目标不是“把整份文档一次性抽成最终 JSON”，而是把标准化文档加工成一组 **字段级可治理对象**，供后续治理层决定这些结果是否允许进入数据库。

这一层当前要围绕下面这条代码主线组织：

```text
backend 聚合后的 all_blocks + task_spec
  -> input_adapter.py
  -> GraphInput
  -> broad extraction
  -> field evidence bundles
  -> resolution agent
      -> 默认先看当前字段 bundle
      -> 必要时调用 field bundle tool
      -> 必要时调用 global lookup tool
  -> result.fields + trace.fields
  -> ExtractionResult(result + trace)
```

可以拆成三件事理解：

1. `broad extraction`
   只为每个字段预选相关 blocks 和证据，不生成最终字段值。
2. `resolution`
   负责字段最终定案；当前字段能否 `resolved`，在这里决定。
3. `tool`
   只服务于 `resolution`，用于按需参考其他字段或做一次全局补查。

这层不直接解决：

- 当前字段该 `pass`、`human_review`、`reject` 还是 `fallback`
- 字段最终如何写数据库
- 人工接管后如何审批或修正

这些属于后续外层治理控制的职责。

## 模块边界

`file_extraction_agent` 的输入不是 `document_processor` 的原始直接返回值，而是 **backend 在 session 维度聚合后的标准化结果**。进入这一层前，外部应当已经完成：

- 原始文件解析
- `blocks` 标准化
- `document_id`、页码、bbox 等定位信息补齐
- 任务级 schema / task spec 确定

这一层不直接接收 `pdf/docx` 文件对象，只接收标准化后的 blocks 主输入。

进入 `file_extraction_agent` 前，当前已经落地一层明确的外部输入适配层：`input_adapter.py`。这层不负责任何 broad / resolution / tool 编排，只负责把外部 session 级输入收敛成稳定的 `GraphInput`。

## 代码结构

当前目录应按下面这个结构理解：

```text
file_extraction_agent/
├── __init__.py
├── input_adapter.py
├── processor.py
├── schemas.py
├── extractor_client.py
├── task_specs/
│   └── *.json
├── impl/
│   ├── graph.py
│   ├── state.py
│   ├── prompts.py
│   ├── broad_extraction.py
│   ├── resolution.py
│   └── tools.py
└── docs/
    ├── DESIGN.md
    └── DEVLOG.md
```

如果当前代码还没完全长成这个样子，应当把这份文档视为后续重构目标，而不是沿用旧的“broad 出 candidate，resolution 只去重”的职责划分。

各层职责如下：

- `input_adapter.py`
  - 负责外部 blocks 输入校验、协议适配和 `GraphInput` 组装
  - 只解决“外面传进来的数据能不能进入 agent 内部契约”
  - 不负责 broad / resolution / tool 调度

- `processor.py`
  - 对外统一入口
  - 接住 session 级调用参数
  - 把外部输入转交给 `input_adapter.py`
  - 再把 `GraphInput + extractor_client` 交给 `impl/graph.py`
  - 返回最终 `ExtractionResult`

- `schemas.py`
  - 定义数据契约
  - 包括 `GraphInput`、字段级 evidence bundle、resolution 输出、tool 输入输出和最终聚合结果

- `extractor_client.py`
  - 负责构造真正可调用的结构化输出执行器
  - broad 与 resolution 都通过它访问模型

- `task_specs/*.json`
  - 保存固定 schema、字段类型、关键字段标记、局部校验规则、cross-field hints、lookup hints

- `impl/graph.py`
  - 只负责编排节点流转
  - 不直接定义对外 API

- `impl/state.py`
  - 定义流程内部执行态
  - 供 graph、broad、resolution、tools 共用

- `impl/prompts.py`
  - 定义 broad extraction 与 resolution agent 的提示词组装逻辑
  - 属于内部执行策略，不对外暴露 prompt override

- `impl/broad_extraction.py`
  - 只负责字段级证据预选
  - 不产最终字段值

- `impl/resolution.py`
  - 负责字段最终定案
  - 默认先看当前字段 broad bundle
  - 必要时调用 tools

- `impl/tools.py`
  - 放 resolution 可调用的内部工具
  - 当前至少包括：
    - `get_field_bundle(...)`
    - `lookup_blocks_for_field(...)`

## 主处理链路

整体流程应当按下面这条 pipeline 落到代码里：

```text
调用方传入 backend 聚合后的 all_blocks、task_spec_name 或 task_spec
  -> processor.extract(...) 先把外部参数交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责 blocks 校验、协议适配和 GraphInput 组装
  -> 如果没传 extractor_client，就要求调用方显式传入 base_url / openai_api_key / model
  -> impl/graph.py 从 GraphInput 开始驱动 broad extraction
  -> broad extraction 一次性为所有字段生成 evidence bundles
  -> resolution 阶段读取全字段 evidence bundles
  -> 对每个目标字段做最终定案
  -> 定案时必要时调用 field bundle tool 或 global lookup tool
  -> 汇总成 ExtractionResult 返回给上层
```

可以概括成：

```text
all_blocks
  -> broad extraction
  -> per-field evidence bundles
  -> resolution
  -> per-field resolved / failed
```

## broad extraction 设计

### broad 的职责

`broad extraction` 的职责不是生成字段最终值，而是：

```text
all blocks
  -> 为每个字段找最相关的 blocks / 证据片段
  -> 组织成字段级 evidence bundle
  -> 把 bundle 交给 resolution
```

因此 broad 更像：

- 字段级证据召回器
- 字段级局部上下文压缩器
- 后续 resolution 的材料准备层

而不是：

- 字段最终定案器
- 最终值生成器
- 写库前裁决器

### broad 的输入

输入包括：

- `GraphInput.blocks`
- `task_spec`
- 可选 `markdown / md_list`

当前主输入应为 `blocks`。`markdown` / `md_list` 只作备用文本，不是主处理链路的一等输入。

### broad 的输出结构

broad 的结构化输出建议以字段为中心组织，每个字段对应一个 `FieldEvidenceBundle`。每个 bundle 至少包含：

- `field_name`
- `relevant_block_ids`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_notes`

其中 `evidence_refs` 应统一记录：

- `document_id`
- `page`
- `span`
- `block_id`

### broad 的约束

- broad **不输出最终字段值**
- broad **不输出用于直接写库的 candidate**
- broad **不在这一层解决跨字段冲突**

如果后续需要保留局部猜测，也只能保留成非常弱语义的调试信息，不能把它设计成主流程依赖对象。主流程的 broad 输出不应包含 `candidate_values` 这类“半定案”结构。

## resolution 设计

### resolution 的职责

`resolution` 是面向目标字段最终定案的执行层。它的职责不是简单去重，而是：

```text
目标字段 bundle
  -> 判断当前字段证据是否足够
  -> 若不足，参考其他字段 bundle
  -> 若仍不足，执行一次全局补查
  -> 结合 schema / cross hints / lookup 结果
  -> 输出 resolved / failed
```

也就是说，这一层真正负责回答的是：

- 当前字段能不能自动定案
- 当前字段最终值是什么
- 当前字段定案时参考了哪些字段
- 当前字段是否执行过补查
- 当前字段为什么成功或失败

### resolution 的实现形式

治理语义上，resolution 是“字段级定案”；实现上不强制必须“每字段单独一次外部模型调用”。

代码层可接受两种落地方式：

1. 在同一个 resolution 阶段内部，按字段逐个组织定案逻辑并返回字段级结果列表。
2. 对少数字段做单独 resolution 调用，但这不是当前第一版的必需条件。

无论采取哪种形式，都必须保证：

- 输出是字段级的
- `used_field_outputs` 可追踪
- `extra_lookup_used` 可追踪
- 每个字段单独有 `reason / failure_reason`

## traceability 设计

### 设计目标

`file_extraction_agent` 相对“端到端直接输出最终字段”的主要优势，不在于“模型没有看全文”，而在于：

```text
系统虽然同样从全局 blocks 开始处理
  -> 但会把字段相关证据预选
  -> 字段间参考
  -> 补查行为
  -> 最终定案原因
显式保存为可追踪对象
```

也就是说，这一层的 traceability 不是自然产生的，而是 **必须通过结构化留痕显式保存**。

如果 broad、resolution、tool 之间只是内部传值，最后没有把这些中间痕迹挂到结果对象或 trace 对象上，那么即使流程分成了两阶段，trace 能力也不会明显强于端到端方案。

### 必须保存的 trace 信息

当前设计要求至少保存下面三层 trace。

#### 第一层：证据选择 trace

对于每个字段，broad 阶段必须显式保存：

- 当前字段从全局 `all_blocks` 中预选出的 `relevant_block_ids`
- 对应 `evidence_texts`
- 对应 `evidence_refs`
- 当前字段的 `local_status`
- 当前字段的 `local_notes`

这层 trace 的目的不是直接给最终答案，而是回答：

- 当前字段相关材料来自哪里
- broad 为什么认为这些 blocks 更值得进入后续 resolution
- broad 是否已经暴露出缺失、歧义或弱证据状态

#### 第二层：字段定案 trace

对于每个字段，resolution 阶段必须显式保存：

- 当前字段最终是否 `resolved / failed`
- 当前字段最终的 `final_value`
- 当前字段在定案时实际使用了哪些字段输出，即 `used_field_outputs`
- 当前字段的 `reason / failure_reason`

这层 trace 的目的，是回答：

- 当前字段最后为什么是这个结果
- 当前字段是否参考了其他字段
- 如果参考了，是哪些字段参与了当前字段定案
- 当前字段失败时，失败原因是什么

#### 第三层：补查 trace

如果当前字段在 resolution 阶段触发全局补查，系统必须显式保存：

- 是否触发过补查，即 `extra_lookup_used`
- 补查触发原因
- 补查使用的 `lookup_hints`
- 补查返回的 block 摘要或 block id
- 补查结果是否真正参与了最终定案

这层 trace 的目的，是回答：

- 当前字段是否只靠 broad 就完成定案
- 当前字段是否因为证据不足而进入了额外查询
- 补查到底补回了什么材料

### traceability 的代码落点

为了让 traceability 不是口头设计而是代码结构约束，当前要求把 trace 信息分别落到下面这些对象里：

- `BroadExtractionOutput`
  - 保存字段级证据选择 trace
- `FieldTraceRecord`
  - 保存字段级定案 trace、cross-field reference 和 lookup trace
- `ExtractionTrace`
  - 汇总所有字段 trace、warnings 和附加元信息

如果后续 broad、resolution 或 tool 增加了新的判断步骤，也应优先评估这些步骤是否需要新增 trace 字段，而不是仅仅把中间信息留在函数局部变量中。

### 对外层治理的意义

显式保存 trace 的意义不只是方便调试，更是为了支撑后续写库前治理。后续外层治理层至少需要利用这些 trace 回答：

- 当前字段的证据来源是否足够清楚
- 当前字段是否参考过其他字段
- 当前字段是否经历过补查仍未定案
- 当前字段失败时，失败属于缺失、冲突还是证据不足

因此，traceability 在这里不是附加特性，而是当前架构成立的前提之一。

## tools 设计

`tool` 不是独立业务模块，而是 resolution 阶段的内部辅助能力。当前至少需要两个 tool。

### Tool 1：`get_field_bundle(field_name)`

作用：

- 读取某个其他字段在 broad 阶段生成的 evidence bundle

输入：

- `field_name`

输出：

- `field_name`
- `relevant_block_ids`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_notes`

用途：

- 当前字段定案时需要 cross-field reference
- 例如：
  - `deadline` 参考 `application_period`
  - `amount` 参考 `currency`
  - `program_name` 参考 `degree_level`

### Tool 2：`lookup_blocks_for_field(...)`

作用：

- 面向当前目标字段，从全局 `all_blocks` 中补充检索一小批更相关的 blocks

输入建议至少包括：

- `target_field_name`
- `query_reason`
- `lookup_hints`
- `top_k`

输出建议至少包括：

- `matched_blocks`
  - `block_id`
  - `document_id`
  - `page_no`
  - `text`
  - `score`
- `applied_hints`
- `lookup_reason`

### tools 的使用顺序

resolution 默认遵循下面这条顺序：

```text
先看当前字段 broad bundle
  -> 若需要 cross，调 get_field_bundle(...)
  -> 若 cross 后仍不足，调 lookup_blocks_for_field(...)
  -> 再做最终 resolved / failed
```

也就是说：

- 先利用已有局部证据
- 再按需参考其他字段
- 最后才做一次全局补查

## Graph 输入与内部状态

`impl/graph.py` 不建议接收大量松散参数，而是只接收一个已经在外部输入适配层确定好的图输入对象和一个抽取执行客户端：

```python
run_extraction_graph(graph_input, extractor_client) -> ExtractionResult
```

图入口固定成 `schemas.py` 中定义的 `GraphInput`，至少包含：

- `blocks`
- `task_spec`
- `run_config`
- `metadata`

其中：

- `blocks`
  是 backend 聚合后的多文档块级输入，每个 block 至少带 `document_id`、`text`、`page_no`、`bbox`、`kind`
- `task_spec`
  是当前任务的固定 schema 定义
- `run_config`
  是流程执行策略，例如是否允许 extra lookup、每字段最多 lookup 次数、是否保留详细 trace
- `metadata`
  是可选任务标签、session 信息或调试信息

对应地，`impl/state.py` 定义图内部中间态，例如：

- `graph_input`
- `broad_output`
- `result_fields`
- `trace_fields`
- `warnings`

推荐的 graph 编排顺序是：

```text
GraphInput + extractor_client
  -> build_graph_state(graph_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state)
  -> ExtractionResult(result + trace)
```

如果 resolution 内部触发 tool，它们也应当只修改当前 `GraphState` 中与 lookup / trace 相关的部分，不应反向修改 broad 的职责语义。

## 结构化 Schema 设计

### broad 输出

第一层结构化输出由 `BroadExtractionOutput` 控制，并以字段为中心组织。每个字段对应一个 evidence bundle，至少包含：

- `field_name`
- `relevant_block_ids`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_notes`

当前设计中，broad 输出 **不包含 `candidate_values`**。

### resolution 输出

第二层结构化输出拆成纯结果与 trace 两部分。

纯结果由 `ResolvedFieldResult` 控制，并且只允许两种结果：

- `resolved`
- `failed`

每个字段至少包含：

- `field_name`
- `status`
- `final_value`

字段级 trace 由 `FieldTraceRecord` 控制，至少包含：

- `field_name`
- `status`
- `broad_trace`
- `used_field_outputs`
- `extra_lookup_used`
- `lookup_trace`
- `reason`
- `failure_reason`

这里的关键字段不是置信度，而是：

- 当前字段最终是否定案成功
- 定案过程中参考过哪些其他字段
- 是否执行过补查
- 为什么成功或失败

### 最终聚合输出

`processor.extract(...)` 最终不应只返回“字段结果列表”，而应返回一个同时包含 **纯结果** 与 **trace 内容** 的顶层对象：

```text
ExtractionResult
  -> result
  -> trace
```

这里要求：

- `result`
  只放最终业务结果，不混入 broad / lookup / reason 这类执行痕迹
- `trace`
  只放 broad、cross-field reference、lookup 和失败原因等留痕信息

推荐结构如下：

```text
ExtractionResult
  -> result: ExtractionContent
       -> fields: ResolvedFieldResult[]
  -> trace: ExtractionTrace
       -> fields: FieldTraceRecord[]
       -> warnings
       -> metadata
```

#### `result` 的职责

`result` 回答的是：

- 当前最终字段结果是什么
- 哪些字段 `resolved`
- 哪些字段 `failed`
- 当前字段最终值是什么

因此 `result.fields` 中的单字段对象应尽量克制，只包含：

- `field_name`
- `status`
- `final_value`

也就是说，`result` 的目标是服务于：

- 后续 route policy
- 最终写库判断
- 上层业务消费

而不是承担审计或调试职责。

#### `trace` 的职责

`trace` 回答的是：

- 当前字段 broad 预选了哪些 blocks
- 当前字段定案时参考了哪些其他字段
- 当前字段有没有触发补查
- 当前字段为什么 resolved / failed

因此 `trace.fields` 中的单字段 trace 对象建议包含：

- `field_name`
- `broad_trace`
- `used_field_outputs`
- `extra_lookup_used`
- `lookup_trace`
- `reason`
- `failure_reason`

其中：

- `broad_trace`
  保存 broad 阶段的字段级证据预选痕迹
- `lookup_trace`
  保存当前字段补查行为
- `reason / failure_reason`
  保存当前字段定案解释

#### broad trace 的建议结构

对于 `trace.fields[].broad_trace`，建议至少保存：

- `relevant_block_ids`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_notes`

这层结构应当直接对应 broad extraction 的主输出语义。

#### lookup trace 的建议结构

对于 `trace.fields[].lookup_trace`，建议每次补查都记录：

- `lookup_reason`
- `lookup_hints`
- `returned_block_ids`
- `returned_refs`
- `used_in_final_decision`

如果字段没有补查，则 `lookup_trace` 为空列表。

#### 这样设计的原因

采用 `result` / `trace` 双层结构的原因是：

- 让最终业务结果保持干净
- 让 trace 可单独扩展而不污染业务结果
- 让 backend 能自然拆分成“结果持久化”和“trace 持久化”

也就是说：

```text
agent 跑完整个流程
  -> 返回 ExtractionResult(result + trace)
  -> backend 决定如何持久化 result 与 trace
```

这里不建议让 `agent service` 直接持久化整个运行状态；更合理的方式是：

- `agent service`
  负责生成 `ExtractionResult`
- `backend`
  负责保存 `result`
  负责保存 `trace`

这样更符合当前仓库的职责边界。

## task spec 设计

`task_specs/*.json` 负责表达固定 schema，而不是把字段规则硬编码到 prompt 里。

每个字段至少定义：

- `field_name`
- `display_name`
- `type`
- `required`
- `critical`
- `allow_missing`
- `validation_rules`
- `cross_field_hints`
- `lookup_hints`

第一版建议先支持有限字段类型：

- `string`
- `date`
- `enum`
- `money`
- `boolean`

这样：

- broad 可以围绕字段 hints 做证据预选
- resolution 可以围绕字段约束做最终定案
- tool 可以围绕字段 hints 做一次定向 lookup

## 与外层治理的关系

`file_extraction_agent` 的职责是把抽取结果变成 **可治理对象**，不直接做最终 route。

因此它必须把这些材料准备完整：

- 每个字段的 evidence bundle
- 证据文本
- 证据位置
- 局部状态
- 定案时参考了哪些其他字段
- 是否执行过 extra lookup
- 最终定案原因或失败原因

后续外层治理层再根据这些结果决定：

- `pass`
- `human_review`
- `reject`
- `fallback`

这种分层可以把“模型产出了什么”和“系统是否允许写库”拆开，避免把写库判断硬塞进抽取链路。

## 测试约束

这一层有行为变化，必须按 TDD 推进。建议至少补这些测试文件，并为每个测试文件同步维护 `tests/docs/` 下的一一对应说明文档：

- `tests/file_extraction_agent/test_schemas.py`
- `tests/file_extraction_agent/test_processor.py`
- `tests/file_extraction_agent/test_broad_extraction.py`
- `tests/file_extraction_agent/test_resolution.py`
- `tests/file_extraction_agent/test_tools.py`
- `tests/file_extraction_agent/test_integration.py`

重点固定这些行为：

- 输入归一化与 task spec 加载
- broad extraction 只返回 evidence bundles，不返回 candidate
- resolution 能读取 broad 全量结果，并对字段级结果做最终收口
- resolution 在需要时能调用 `get_field_bundle(...)`
- resolution 在需要时能调用 `lookup_blocks_for_field(...)`
- 最终结果可追踪到 evidence、used field outputs 和 lookup trace

## 文档同步要求

实现落地时，除了代码和测试，还需要同步维护：

- 当前这份 `docs/DESIGN.md`
- 对应测试文件的一一对应测试文档

如果后续需要补 `docs/DEVLOG.md`，必须先向用户说明：

- 要更新哪个 `DEVLOG.md`
- 准备记录什么
- 会采用什么格式

在获得批准后才能编辑。
