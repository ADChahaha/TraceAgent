# File Extraction Agent Design

这份文档面向开发者，说明 `file_extraction_agent` 在 `agent service` 中的代码结构、模块边界和主处理链路。它处理的是 **标准化后的文档 blocks 上的字段级证据预选与字段最终定案**，不负责原始文件解析，也不直接负责写库、外层 route policy 或人工审核流转。

## 目标

`file_extraction_agent` 的目标不是“把整份文档一次性抽成最终 JSON”，而是把标准化文档加工成一组 **字段级可治理对象**，供后续治理层决定这些结果是否允许进入数据库。

这一层当前要围绕下面这条代码主线组织：

```text
backend 聚合后的 all_blocks + task_spec
  -> input_adapter.py
  -> impl/schemas.py 中的 ExtractionInput
  -> broad extraction
  -> impl/schemas.py 中的 FieldEvidence[]
  -> resolution agent
      -> 默认先看当前字段 evidence
      -> 必要时调用 field bundle tool
      -> 必要时调用 global lookup tool
  -> graph.py 把内部决策对象映射成对外 ExtractionResult
  -> schemas.py 中的 ExtractionResult(result + trace)
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

进入 `file_extraction_agent` 前，当前已经落地一层明确的外部输入适配层：`input_adapter.py`。这层不负责任何 broad / resolution / tool 编排，只负责把外部 session 级输入收敛成稳定的**内部图输入对象**。

## 代码结构

当前目录应按下面这个结构理解：

```text
file_extraction_agent/
├── __init__.py
├── input_adapter.py
├── processor.py
├── schemas.py
├── extractor_client.py
├── impl/
│   ├── schemas.py
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
  - 负责外部 blocks 输入校验、协议适配和内部 `ExtractionInput` 组装
  - 只解决“外面传进来的数据能不能进入 agent 内部契约”
  - 不负责 broad / resolution / tool 调度

- `processor.py`
  - 对外统一入口
  - 接住 session 级调用参数
  - 把外部输入转交给 `input_adapter.py`
  - 再把内部 `ExtractionInput` 和模型调用依赖 `ExtractorClient` 交给 `impl/graph.py`
  - 返回最终 `ExtractionResult`

- `schemas.py`
  - 只定义**外部稳定契约**
  - 包括调用方传入的稳定输入对象、task spec、标准化 block、最终 `ExtractionResult`
  - 不直接暴露 `broad / resolution / lookup` 这些实现阶段名

- `extractor_client.py`
  - 负责构造真正可调用的结构化输出执行器
  - 最后返回一个可以直接 `invoke(...)` 的模型调用器 `ExtractorClient`
  - 只解决“如何按给定 schema 调模型并拿到结构化结果”
  - broad 与 resolution 节点都通过这个可调用器访问模型
  - 不负责 graph 编排，也不负责拼装 LangGraph 流程

- `impl/schemas.py`
  - 定义**内部流程契约**
  - 包括 `RunOptions`、`ExtractionInput`、`FieldEvidence`、`EvidenceCollection`、`FieldDecision`、`LookupRecord`
  - 这些对象服务于当前实现链路，不应直接当作外部长期稳定 API

- `impl/graph.py`
  - 只负责编排节点流转
  - 不直接定义对外 API
  - 负责把内部流程对象收口并映射成 `schemas.py` 中的最终返回
  - 当前 broad / resolution 的串联顺序由它决定，而不是由 `ExtractorClient` 决定

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

## 契约分层原则

这一层后续重构时，必须把“对外稳定契约”和“当前实现专用契约”拆开。

### `schemas.py` 应回答什么

`schemas.py` 只回答下面两个问题：

1. 调用方要按什么稳定格式把数据交给 `file_extraction_agent`
2. `file_extraction_agent` 最终会按什么稳定格式把结果回给上层

也就是说，`schemas.py` 应当优先承载：

- `FieldDefinition`
- `TaskSpec`
- `NormalizedBoundingBox`
- `NormalizedBlock`
- `FieldEvidenceRef`
- `ExtractionResult`
- `ExtractionResult` 里真正面向上层消费的 `result` / `trace` 子对象

这些对象的命名应避免直接泄漏当前 pipeline 阶段名。像 `BroadTrace`、`ResolvedFieldResult`、`LookupTraceRecord` 这种带实现步骤色彩的名字，不适合作为长期稳定外部契约。

### `impl/schemas.py` 应回答什么

`impl/schemas.py` 只回答下面这个问题：

```text
当前这版 broad -> resolution -> tool 流程
  -> 每一步内部到底传什么对象
  -> 每一步内部到底产什么对象
  -> graph 最后怎么把它们映射成外部结果
```

因此，下面这类对象更适合下沉到 `impl/schemas.py`：

- `RunOptions`
- `ExtractionInput`
- `FieldEvidence`
- `EvidenceCollection`
- `FieldDecision`
- `LookupRecord`
- 任何仅为内部编排存在的 trace 明细对象

如果将来实现从 `broad -> resolution -> lookup` 换成别的链路，应该优先改 `impl/schemas.py`，而不是把 `schemas.py` 连同上层调用方一起拖着重命名。

## 主处理链路

整体流程应当按下面这条 pipeline 落到代码里：

```text
调用方传入 backend 聚合后的 all_blocks、task_spec_name 或 task_spec
  -> processor.extract(...) 先把外部参数交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责 blocks 校验、协议适配和 impl/schemas.py::ExtractionInput 组装
  -> 如果没传 extractor_client，就优先用显式 base_url / openai_api_key / model 构造模型调用器；缺省时读取 BASE_URL / OPENAI_API_KEY / MODEL，MODEL 仍缺省时使用默认模型
  -> impl/graph.py 从内部 ExtractionInput 开始驱动 broad extraction
  -> broad / resolution 节点内部再通过 extractor_client 发起结构化模型调用
  -> broad extraction 一次性为所有字段生成 evidence bundles
  -> resolution 阶段读取全字段 evidence bundles
  -> 对每个目标字段做最终定案
  -> 定案时必要时调用 field bundle tool 或 global lookup tool
  -> graph.py 把内部 broad / resolution / lookup 痕迹映射成外部 ExtractionResult
  -> 返回给上层
```

可以概括成：

```text
all_blocks
  -> broad extraction
  -> per-field evidence bundles
  -> resolution
  -> per-field resolved / failed
```

## 模型与处理单元施工图

这一节是当前实现的施工图。后续改代码时，优先让代码和测试贴合这里，而不是只看函数名猜职责。

整体链路按下面的对象流动：

```text
NormalizedBlock[] + TaskSpec
  -> input_adapter.build_graph_input(...)
  -> ExtractionInput(blocks, task_spec, options, metadata)
  -> broad model
  -> EvidenceCollection(FieldEvidence[])
  -> broad 输出校验
  -> resolution model per field
      -> 可请求 get_field_bundle(...)
      -> 可请求 lookup_blocks_for_field(...)
      -> 必须最终返回轻量字段判断 FieldResolutionDecision
  -> 系统按 used_block_ids 绑定 FieldEvidence
  -> validation rule executor
  -> FieldDecision[]
  -> graph mapper
  -> ExtractionResult(result.fields[] + trace.fields[])
```

### 处理单元 1：input adapter

实现位置：`input_adapter.py`

输入：

- 调用方传入的 `blocks`
- `task_spec` 或 `task_spec_name`
- 可选 `markdown / md_list`
- 可选 `run_options`
- 可选 `metadata`

处理步骤：

```text
外部调用参数
  -> 检查 task_spec 与 task_spec_name 至少有一个存在
  -> 如果传了 task_spec，直接使用
  -> 如果只传 task_spec_name，从 task_specs/<name>.json 加载
  -> 用 Pydantic 把 blocks / task_spec 归一化成内部对象
  -> 填充默认 RunOptions 和 metadata
  -> 返回 ExtractionInput
```

失败条件：

- 没有传 `task_spec` 或 `task_spec_name`，抛 `ValueError`
- `task_spec_name` 找不到对应 JSON，抛 `TaskSpecNotFoundError`
- 字段定义重复、block 结构不合法等由 Pydantic 校验抛出

### 处理单元 2：broad model

实现位置：`impl/broad_extraction.py` 与 `impl/prompts.py::build_broad_extraction_messages(...)`

职责：

- 从全量 `blocks` 中为每个 schema 字段预选证据
- 输出字段级 `FieldEvidence`
- 不生成最终字段值
- 不决定 route
- 不写库

模型输入：

- `task_name`
- `TaskSpec.fields[]`
- 全量 `NormalizedBlock[]`
- `RunOptions`
- `metadata`

模型输出：

- `EvidenceCollection.fields[]`
- 每个 `FieldEvidence` 至少包含：
  - `field_name`
  - `relevant_block_ids`
  - `evidence_texts`
  - `evidence_refs`
  - `local_status`
  - `local_notes`

broad 输出后的代码校验必须执行：

```text
EvidenceCollection
  -> 提取 task_spec.fields 中声明的字段集合
  -> 检查 broad 是否返回重复 field_name
  -> 检查 broad 是否返回 schema 外 field_name
  -> 检查 broad 是否覆盖所有 task_spec 字段
  -> 提取 ExtractionInput.blocks 中可引用的 block_id 集合
  -> 检查 relevant_block_ids / evidence_refs.block_id 是否都来自输入 blocks
  -> 校验通过后写入 GraphState.evidence_collection
```

失败条件：

- broad 少返回字段：抛 `ValueError("missing broad evidence fields: ...")`
- broad 返回 schema 外字段：抛 `ValueError("unknown broad evidence fields: ...")`
- broad 返回重复字段：抛 `ValueError("duplicate broad evidence fields: ...")`
- broad 引用了不存在的 block：抛 `ValueError("unknown broad evidence block ids: ...")`

这一步的意义是：模型可以犯错，但进入 resolution 之前，字段集合和证据引用必须先被系统校验。

### 处理单元 3：resolution model

实现位置：`impl/resolution.py` 与 `impl/prompts.py::build_field_resolution_messages(...)`

职责：

- 对单个目标字段做最终定案
- 默认只读取 broad 阶段压缩后的 evidence
- 根据需要显式请求工具
- 最终只返回轻量字段判断，不直接构造系统内部 `FieldDecision`

模型输入：

- 当前 `target_field_name`
- 当前目标字段的 schema 定义
- 当前目标字段的 broad evidence 摘要
- 全字段 `all_field_evidence`
- 已有 `tool_evidence`
- 已有 `tool_records`

resolution 模型默认**不直接接收原始 `blocks`**。原始 `blocks` 只能由工具或规则执行器访问。

模型输出边界必须保持轻量：

```text
FieldResolutionAction(action=final_decision)
  -> decision.status
  -> decision.value
  -> decision.used_block_ids
  -> decision.related_fields
  -> decision.reason / failure_reason
```

模型不负责输出：

- `FieldEvidence`
- `FieldEvidenceRef`
- `LookupRecord`
- `FieldReferenceRecord`
- `TraceAction`

这些对象都由系统根据 `used_block_ids`、工具记录和规则执行结果组装。

处理步骤：

```text
目标字段 field
  -> 构造只包含 field schema、目标字段 evidence、全字段 evidence 摘要的 prompt
  -> extractor_client.invoke(output_schema=FieldResolutionAction)
  -> 如果 action=final_decision，读取轻量 action.decision
  -> 用 decision.used_block_ids 从 ExtractionInput.blocks 回查 block 文本、页码和 bbox
  -> 系统组装 FieldEvidence 和 FieldDecision
  -> 如果 action=get_field_bundle，执行 field bundle tool，再把 tool evidence 交回下一轮模型
  -> 如果 action=lookup_blocks，执行 global lookup tool，再把 lookup evidence / record 交回下一轮模型
  -> 重复直到模型返回 final_decision 或超过工具调用限制
  -> 对 FieldDecision 应用 validation_rules
  -> 返回最终 FieldDecision
```

失败条件：

- resolution 开始前没有 `EvidenceCollection`，抛 `ValueError`
- 没有传 `extractor_client`，抛 `ValueError`
- 模型返回的 `target_field_name` 与当前字段不一致，抛 `ValueError`
- 模型返回了输入中不存在的 `used_block_ids`，抛 `ValueError`
- 模型请求工具次数超过限制，抛 `ValueError`
- 禁用 extra lookup 时模型请求 `lookup_blocks`，抛 `ValueError`

### 处理单元 4：field bundle tool

实现位置：`impl/tools.py::get_field_bundle(...)`

职责：

- 让 resolution 模型显式读取某个其他字段的 broad evidence
- 服务于跨字段参考
- 不产出最终字段值

输入：

- `EvidenceCollection`
- `requested_field_name`

处理步骤：

```text
requested_field_name
  -> 在 EvidenceCollection.fields 中查找同名 FieldEvidence
  -> 找到则返回该 FieldEvidence，并把该 bundle 加入下一轮 tool_evidence
  -> 找不到则返回 None，但仍把“未命中”作为 tool_records 交回下一轮模型
  -> 无论是否找到，都记录一条 field_reference action
```

trace 要求：

- 只要模型请求过 `get_field_bundle(...)`，系统就必须记录 `field_reference` action
- action 中至少记录：
  - 请求的字段名
  - 是否找到 bundle
  - 返回证据的 refs
  - 工具结果是否已经返回给模型
  - 是否被模型最终声明为使用

这里区分两件事：

```text
系统可证明：模型显式请求过某字段 bundle
模型声明：最终定案时参考了哪些字段
```

### 处理单元 5：global lookup tool

实现位置：`impl/tools.py::lookup_blocks_for_field(...)`

职责：

- 当模型认为 broad evidence 不够完整时，从全量 `blocks` 中定向补查
- 返回一小批补充证据
- 记录 lookup trace
- 不直接产出最终字段值

输入：

- 全量 `NormalizedBlock[]`
- `target_field_name`
- `query_reason`
- `lookup_hints`
- `lookup_top_k`

处理步骤：

```text
target_field_name + lookup_hints
  -> 对全量 blocks 做轻量相关性打分
  -> 按分数和原顺序排序
  -> 返回 top_k matched_blocks
  -> 生成 LookupRecord(returned_to_model=True, used_in_final_decision=False)
  -> 把 matched_blocks 转成 tool_evidence
  -> 下一轮 resolution model 再决定最终 FieldDecision
```

配置要求：

- `allow_extra_lookup`：是否允许模型请求 lookup
- `max_lookup_calls_per_field`：每个字段最多允许几次 lookup 调用
- `lookup_top_k`：每次 lookup 最多返回几个 blocks

这三个配置不能混用。lookup 调用次数和每次返回条数必须分开表达。

trace 语义：

- `returned_to_model=True` 表示 lookup 结果确实被传给了模型
- `used_in_final_decision=True` 只能来自模型最终声明或后续规则显式确认，不能在 lookup 调用时直接写死

### 处理单元 6：validation rule executor

实现位置：`impl/resolution.py::_apply_validation_rules(...)`

职责：

- 在模型给出 `FieldDecision` 后，执行 task spec 中声明的通用规则
- 做结构化校验、规则覆盖或跨字段一致性收口
- 不代替模型发起字段定案

输入：

- 模型返回的 `FieldDecision`
- 当前 `FieldDefinition.validation_rules`
- `GraphState`
- 已完成的 `prior_decisions`

处理步骤：

```text
FieldDecision + validation_rules
  -> 如果没有 validation_rules，原样返回 FieldDecision
  -> 如果 source_type=table_rows，从全量 blocks 中按声明的 columns/filter/exclude/target_column 选行
  -> 将命中行转成 evidence，并覆盖模型混入的无关结果
  -> 记录 validation_rule action，说明规则访问了 blocks 并覆盖/校正了模型结果
  -> 如果 operation=count_items，从 source_field 的已定案结果计算条目数
  -> 记录 validation_rule action，说明结果来自跨字段计数
  -> 返回新的 FieldDecision
```

规则层访问全量 `blocks` 是允许的，但必须满足两个条件：

1. 只能由 `TaskSpec.fields[].validation_rules` 显式声明触发。
2. 必须在 trace action 中记录 `validation_rule`，说明访问原因、规则类型和证据来源。

这和 lookup 的区别是：

```text
lookup_blocks_for_field
  -> 模型主动请求的补查行为

validation_rules
  -> schema 声明的确定性规则校验 / 覆盖行为
```

### 处理单元 7：graph mapper

实现位置：`impl/graph.py`

职责：

- 串联 broad 和 resolution
- 不做业务抽取
- 不做 route
- 不访问数据库
- 把内部 `FieldDecision[]` 映射为外部 `ExtractionResult`

处理步骤：

```text
ExtractionInput
  -> build_graph_state(...)
  -> run_broad_extraction(...)
  -> run_resolution(...)
  -> FieldDecision.to_field_result()
  -> FieldDecision.to_field_trace()
  -> ExtractionResult(result, trace)
```

输出给上层的内容必须分成两类：

- `result.fields[]`：字段名、状态、最终值
- `trace.fields[]`：证据、相关字段、actions、reason / failure_reason

## Trace Action 语义

`trace.fields[].actions[]` 用来记录系统可证明发生过的处理动作。它不是模型自由生成的解释文本。

当前 action 类型至少包括：

- `field_reference`
  - resolution 模型显式请求了其他字段的 evidence bundle
  - metadata 中记录 `requested_field_name`、是否找到 bundle
- `global_lookup`
  - resolution 模型显式请求了全量 blocks 补查
  - metadata 中记录 `lookup_hints`、`returned_block_ids`、`returned_to_model`
- `validation_rule`
  - schema 声明的规则访问了 blocks 或其他字段结果，并校正/覆盖了模型结果
  - metadata 中记录 `rule_type`、`source_field`、`matched_block_ids`

`related_fields` 与 `actions` 的关系：

```text
related_fields
  -> 模型最终声明当前字段定案参考过哪些字段

actions
  -> 系统可证明执行过哪些工具或规则动作
```

因此，`related_fields` 可以作为解释，但不能替代 `field_reference` action。

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

- `impl/schemas.py::ExtractionInput.blocks`
- `task_spec`
- 可选 `markdown / md_list`

当前主输入应为 `blocks`。`markdown` / `md_list` 只作备用文本，不是主处理链路的一等输入。

### broad 的输出结构

broad 的结构化输出建议以字段为中心组织，每个字段对应一个内部 `FieldEvidence`。每个对象至少包含：

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
目标字段 broad bundle + 全字段 evidence 摘要 + task spec 字段约束
  -> 调用模型判断当前 broad 证据是否足够定案
  -> 如果模型认为证据足够，模型输出轻量 FieldResolutionDecision(resolved / failed)
  -> 如果模型认为 broad 给出的 blocks 不够完整，模型输出 tool_request
  -> 系统按 tool_request 调用 get_field_bundle(...) 或 lookup_blocks_for_field(...)
  -> 把 tool 返回的补充证据重新交给模型
  -> 模型输出最终轻量 FieldResolutionDecision(resolved / failed)
  -> 系统按 used_block_ids 绑定 evidence 并生成内部 FieldDecision
```

这里需要特别注意输入边界：resolution 模型默认不直接接收原始 `blocks`。
它只能看到 broad 阶段已经压缩出的目标字段 evidence、全字段 evidence 摘要、
以及工具返回的补充 evidence。只有当模型显式请求 `lookup_blocks_for_field(...)`
时，系统才允许工具从全量 `blocks` 中定向补查，并把补查结果作为 `tool_evidence`
进入下一轮 resolution。这样可以避免模型绕过 lookup trace 直接回查全文，确保补查行为可追踪。

也就是说，这一层真正负责回答的是：

- 当前字段能不能自动定案
- 当前字段最终值是什么
- 当前字段定案时参考了哪些字段
- 当前字段是否执行过补查
- 当前字段为什么成功或失败

如果字段在 `TaskSpec.fields[].validation_rules` 中声明了通用规则，resolution 必须把这些规则视为字段级约束，而不是把规则硬编码在代码里。当前支持的规则方向包括：

- `source_type=table_rows`：按声明的 `columns`、`filter`、`exclude` 和 `target_column` 从标准化表格行中筛选最小证据片段，并可覆盖模型混入的无关行。
- `operation=count_items`：按 `source_field` 的结果条目数生成计数字段，用于保证列表字段和数量字段一致。

规则执行应保持通用：代码只理解 `validation_rules` 的结构，不认识具体业务词，比如“文明寝室”或“模范寝室”。具体业务条件必须放在 task spec 中。

注意：`resolution` 的字段最终语义判断必须由模型完成。代码不能在未调用模型的情况下，把 broad 阶段的 `evidence_texts` 直接改写成最终值；也不能因为 broad 缺证据就自动执行 lookup 并自行定案。代码可以根据模型给出的 `used_block_ids` 绑定证据和 trace，但不能替代模型决定字段值。规则层只能作为模型输出后的通用约束校验或 trace 补强，不能替代模型做字段值判断。

### resolution 的实现形式

治理语义上，resolution 是“字段级定案”；实现上当前必须按字段组织模型调用，让模型逐字段决定是否已有足够证据，以及是否需要工具补充证据。

代码层当前固定为下面的落地方式：

1. 对 `TaskSpec.fields` 中的每个字段发起一次模型 resolution 请求。
2. 模型返回最终轻量 `FieldResolutionDecision` 时，系统用 `used_block_ids` 生成内部 `FieldEvidence / FieldDecision`，再进入规则校验与结果收口。
3. 模型返回 tool request 时，系统只执行被模型请求的工具，并把工具结果追加回该字段的下一次模型请求。
4. 工具调用结束后，仍然必须由模型输出最终轻量字段判断，系统不根据工具返回内容自行定案。

无论采取哪种形式，都必须保证：

- 输出是字段级的
- 模型声明的 `related_fields` 可保留
- 系统可证明的 `field_reference / global_lookup / validation_rule` action 可追踪
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
- 当前字段定案时模型声明参考了哪些字段，即 `related_fields`
- 当前字段定案过程中系统实际执行了哪些可证明动作，即 `actions`
- 当前字段的 `reason / failure_reason`

这层 trace 的目的，是回答：

- 当前字段最后为什么是这个结果
- 模型最终声明参考了哪些其他字段
- 系统是否真的执行过 field bundle 读取、global lookup 或 validation rule
- 当前字段失败时，失败原因是什么

#### 第三层：补查 trace

如果当前字段在 resolution 阶段触发全局补查，系统必须显式保存：

- 是否触发过补查，即 `global_lookup` action
- 补查触发原因
- 补查使用的 `lookup_hints`
- 补查返回的 block 摘要或 block id
- 补查结果是否已经返回给模型
- 补查结果是否被模型最终声明用于定案

这层 trace 的目的，是回答：

- 当前字段是否只靠 broad 就完成定案
- 当前字段是否因为证据不足而进入了额外查询
- 补查到底补回了什么材料

### traceability 的代码落点

为了让 traceability 不是口头设计而是代码结构约束，当前要求把 trace 信息分两层保存：

- `impl/schemas.py` 中的内部对象
  - 保存 broad 阶段证据预选、resolution 决策和 lookup 明细
  - 允许继续使用带阶段语义的对象名
- `schemas.py` 中的 `ExtractionResult.trace`
  - 汇总字段级审计摘要、warnings 和附加元信息
  - 对外只暴露稳定的证据 / 参考字段 / action / reason 语义

如果后续 broad、resolution 或 tool 增加了新的判断步骤，也应优先评估这些步骤：

```text
先落到 impl/schemas.py 的内部 trace 对象
  -> 再决定是否需要映射成对外 trace.actions[] 或其他稳定字段
```

而不是把新的实现细节直接塞进 `schemas.py`。

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
- 一条 `field_reference` action，记录模型请求过哪个字段 bundle

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
- `lookup_top_k`

输出建议至少包括：

- `matched_blocks`
  - `block_id`
  - `document_id`
  - `page_no`
  - `text`
  - `score`
- `applied_hints`
- `lookup_reason`
- 一条 `global_lookup` action / record，记录返回给模型的 block id 与 refs

### tools 的使用顺序

resolution 默认遵循下面这条顺序：

```text
模型先看当前字段 broad bundle
  -> 模型认为需要 cross-field evidence 时，请求 get_field_bundle(...)
  -> 模型认为 broad blocks 不完整时，请求 lookup_blocks_for_field(...)
  -> 系统执行模型请求的 tool，并记录 LookupRecord / tool evidence
  -> 模型基于原始 broad evidence + tool evidence 做最终 resolved / failed
```

也就是说：

- 是否使用 tool 由模型判断，不由本地规则根据“缺 evidence”自动触发
- tool 只补充模型认为缺失的 evidence，不直接产出最终字段值
- lookup 的典型触发条件是：模型认为 broad 阶段给到的 blocks 不够完整，需要从全量 blocks 定向补查
- field bundle tool 和 global lookup tool 都必须留下 trace action，不能只把 evidence 作为内部变量传递

## Graph 输入与内部状态

`impl/graph.py` 不建议接收大量松散参数，而是只接收一个已经在外部输入适配层确定好的**内部图输入对象**和一个模型调用依赖：

```python
run_extraction_graph(graph_input, extractor_client) -> ExtractionResult
```

图入口固定成 `impl/schemas.py` 中定义的 `ExtractionInput`，至少包含：

- `blocks`
- `task_spec`
- `options`
- `metadata`

其中：

- `blocks`
  是 backend 聚合后的多文档块级输入，每个 block 至少带 `document_id`、`text`、`page_no`、`bbox`、`kind`
- `task_spec`
  是当前任务的固定 schema 定义
- `options`
  是流程执行策略，例如是否允许 extra lookup、每字段最多 lookup 调用次数、每次 lookup 返回条数、是否保留详细 trace
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
ExtractionInput + ExtractorClient
  -> build_graph_state(extraction_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state, extractor_client)
  -> ExtractionResult(result + trace)
```

如果 resolution 内部触发 tool，它们也应当只修改当前 `GraphState` 中与 lookup / trace 相关的部分，不应反向修改 broad 的职责语义。

## 结构化契约设计

这一层后续应明确分成两套契约：

1. `schemas.py`：对外稳定契约
2. `impl/schemas.py`：内部流程契约

### 对外稳定契约：`schemas.py`

`schemas.py` 不应该直接暴露当前内部 pipeline 的步骤名。它应该只表达：

```text
调用方传什么
  -> agent 最终回什么
```

因此，对外稳定契约建议保持下面这个方向：

#### 输入侧

- `FieldDefinition`
- `TaskSpec`
- `NormalizedBoundingBox`
- `NormalizedBlock`
- `FieldEvidenceRef`

这些对象描述的是任务字段、标准化块和证据定位，本身不依赖当前 broad / resolution / lookup 的实现顺序。

#### 输出侧

顶层仍然建议保留：

```text
ExtractionResult
  -> result
  -> trace
```

但 `result` 和 `trace` 里的子对象命名与字段名，应当尽量避免直接暴露：

- `BroadTrace`
- `ResolvedFieldResult`
- `LookupTraceRecord`
- `FieldTraceRecord`

这类带强实现色彩的名字。

更稳定的外部输出语义应该是：

```text
ExtractionResult
  -> result.fields[]
       -> field_name
       -> status
       -> value
  -> trace.fields[]
       -> field_name
       -> evidence
       -> related_fields
       -> actions
       -> reason
       -> failure_reason
  -> trace.warnings
  -> trace.metadata
```

这里的设计重点是：

- `result.fields[]`
  - 只表达最终业务结果
  - 不携带 broad / lookup / resolution 的内部阶段对象
- `trace.fields[]`
  - 只表达“这个字段最终为什么得到这个结果”
  - 可以保留证据、参考字段、动作列表和说明
  - 但不强制把当前内部类名原样暴露出去

#### `trace.actions[]` 的建议语义

如果外层确实需要知道内部发生过什么，建议用**阶段无关的动作列表**表达，而不是直接把内部类名塞到 `schemas.py`。

例如：

- `action_type = "field_reference"`
- `action_type = "global_lookup"`
- `action_type = "validation_rule"`

每条 action 至少可以包含：

- `action_type`
- `message`
- `refs`
- `used_in_final_decision`
- `metadata`

这样外层能看到“做过什么”，但不会和当前内部类名强耦合。

### 内部流程契约：`impl/schemas.py`

`impl/schemas.py` 承载当前实现链路真正需要的细粒度对象。

推荐把下面这些对象下沉到这一层：

- `RunOptions`
- `ExtractionInput`
- `FieldEvidence`
- `EvidenceCollection`
- broad 阶段专用 trace 对象
- `FieldDecision`
- `LookupRecord`
- `FieldReferenceRecord` 或等价的内部工具动作记录

这一层允许显式带出当前 pipeline 阶段语义，因为它本来就是服务于内部实现。

#### 内部流程的推荐链路

```text
processor.extract(...)
  -> input_adapter.build_graph_input(...)
  -> impl/schemas.py::ExtractionInput
  -> broad_extraction.py 产出 FieldEvidence[]
  -> resolution.py 读取 bundles 并生成内部决策对象
  -> tools.py 按需补充 field reference / global lookup 记录
  -> graph.py 把内部对象映射成 schemas.py::ExtractionResult
```

#### broad 输出在内部如何表达

第一层结构化输出仍然以字段为中心组织，但它属于内部契约。每个内部 `FieldEvidence` 至少包含：

- `field_name`
- `relevant_block_ids`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_notes`

当前设计中，broad 输出 **不包含 `candidate_values`**。

#### resolution 在内部如何表达

resolution 阶段内部需要回答的是：

- 当前字段最终能否定案
- 当前字段最终值是什么
- 当前字段定案时参考了哪些其他字段
- 当前字段是否触发过补查
- 当前字段为什么成功或失败

这些信息都可以先保留在内部决策对象里；最后再由 `graph.py` 按外部稳定契约收口。

当前实现还需要一个仅供 resolution 内部使用的模型动作对象，用来表达“模型已经能最终定案”还是“模型要求先调用工具补充证据”。该对象不属于外部 API；如果模型请求工具，系统执行工具后必须再次请求模型输出轻量字段判断。

模型返回的轻量字段判断不包含完整 `FieldEvidence`，只包含最小可追踪依据：

```text
FieldResolutionDecision
  -> status
  -> value
  -> used_block_ids
  -> related_fields
  -> reason / failure_reason
```

系统再执行：

```text
used_block_ids
  -> 从 ExtractionInput.blocks 查找 NormalizedBlock
  -> 生成 FieldEvidence.relevant_block_ids
  -> 生成 evidence_texts
  -> 生成 FieldEvidenceRef(document_id, page, block_id)
  -> 组装内部 FieldDecision
```

#### RunOptions 当前字段

`RunOptions` 必须把不同控制维度拆开，避免一个字段同时表达多件事：

- `allow_extra_lookup`
  - 是否允许 resolution 模型请求 `lookup_blocks_for_field(...)`
- `max_lookup_calls_per_field`
  - 每个目标字段最多允许几次 global lookup 调用
- `lookup_top_k`
  - 每次 global lookup 最多返回几个 blocks
- `keep_detailed_trace`
  - 是否保留更详细的内部调试信息；如果当前版本暂未展开详细 trace，也要在文档中说明它是预留开关

不再把 `max_lookup_calls_per_field` 和 `lookup_top_k` 混在同一个字段里。

#### 内部工具记录对象

resolution 内部至少需要保存两类工具记录：

```text
FieldReferenceRecord
  -> target_field_name
  -> requested_field_name
  -> found
  -> returned_refs
  -> returned_to_model
  -> used_in_final_decision

LookupRecord
  -> target_field_name
  -> lookup_reason
  -> lookup_hints
  -> returned_block_ids
  -> returned_refs
  -> returned_to_model
  -> used_in_final_decision
```

其中：

- `returned_to_model`
  表示系统确实把工具结果传回了下一轮模型。
- `used_in_final_decision`
  表示模型最终声明使用了该工具结果，或者规则层明确基于该工具结果完成覆盖。

二者不能混用。

#### 内部契约的命名约束

内部流程契约建议优先使用常见、短路径的名字，而不是把阶段词堆进类名。

推荐命名方向：

- `RunOptions`
  - 表达执行选项，而不是 `RunConfig`
- `ExtractionInput`
  - 表达进入流程的输入，而不是 `GraphInput`
- `FieldEvidence`
  - 表达单字段证据，而不是 `FieldEvidenceBundle`
- `EvidenceCollection`
  - 表达整批证据结果，而不是 `BroadExtractionOutput`
- `FieldDecision`
  - 表达字段定案结果，而不是带 `resolved` 阶段词的对象名
- `LookupRecord`
  - 表达补查记录，而不是带 `trace record` 的长名字

对应字段名也建议尽量使用常见词：

- `field`
- `value`
- `status`
- `reason`
- `notes`
- `refs`
- `actions`
- `options`

而不是优先使用：

- `broad_trace`
- `resolved_field_result`
- `lookup_trace_record`

这类把内部阶段信息直接写死在名字里的形式。

#### 为什么要这样拆

采用这套拆法的原因是：

- 让 `schemas.py` 对上层保持稳定
- 让 `impl/schemas.py` 能跟着实现自由演进
- 让内部可以继续保留 broad / resolution / lookup 的细节
- 避免把当前实现阶段名永久写进公共返回结构

也就是说：

```text
内部可以继续是 broad -> resolution -> lookup
  -> 但对外只承诺 ExtractionResult 这类稳定结果语义
  -> 将来内部改编排时，不需要强迫上层一起改名
```

### 最终聚合输出的职责边界

`processor.extract(...)` 最终仍然返回 `ExtractionResult(result + trace)`，但职责边界应收紧为：

- `result`
  - 服务于 route policy、写库判断和上层业务消费
  - 不直接挂内部流程对象
- `trace`
  - 服务于审计、调试和治理
  - 允许保留证据、参考字段、动作摘要和失败原因
  - 不要求外层理解当前内部每一个类名

这样更符合当前仓库的职责边界：

```text
agent 跑完整个流程
  -> 返回对外稳定的 ExtractionResult
  -> backend 决定如何持久化 result 与 trace
```

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
- broad 输出必须覆盖所有 task spec 字段，且不能引用不存在的 block
- resolution 能读取 broad 全量结果，并对字段级结果做最终收口
- resolution 必须调用模型完成字段定案，不能无模型走本地 evidence 兜底
- resolution 只有在模型请求时才调用 `get_field_bundle(...)` 或 `lookup_blocks_for_field(...)`
- `max_lookup_calls_per_field` 只限制 lookup 调用次数，`lookup_top_k` 只限制每次 lookup 返回条数
- 最终结果可追踪到 evidence、`related_fields` 和 `field_reference / global_lookup / validation_rule` actions

## 文档同步要求

实现落地时，除了代码和测试，还需要同步维护：

- 当前这份 `docs/DESIGN.md`
- 对应测试文件的一一对应测试文档

如果后续需要补 `docs/DEVLOG.md`，必须先向用户说明：

- 要更新哪个 `DEVLOG.md`
- 准备记录什么
- 会采用什么格式

在获得批准后才能编辑。
