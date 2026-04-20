# File Extraction Agent Design

这份文档面向开发者，说明 `file_extraction_agent` 在 `agent service` 里的职责边界、目录分层和主处理链路。它处理的是 **标准化后的文档内容上的字段抽取与字段定案**，不负责原始文件解析，也不直接负责写库或外层路由判定。

## 目标

`file_extraction_agent` 的目标不是“把整份文档一次性抽成最终 JSON”，而是把文档处理成一组 **字段级可治理对象**，供后续治理层决定这些结果是否允许进入数据库。

这一层当前只负责两件事：

1. broad extraction：围绕固定 schema，为每个字段生成候选、证据和局部状态。
2. field resolution：针对单个目标字段，读取全局字段候选并完成最终定案或失败收口。

也就是说，这一层解决的是：

- 当前字段有什么候选值
- 这些候选来自哪里
- 证据够不够
- 当前字段最终能不能被可靠定案

它不直接解决：

- 当前字段该 `pass`、`review`、`reject` 还是 `fallback`
- 字段最终如何写数据库

这些属于后续外层治理控制的职责。

## 模块边界

`file_extraction_agent` 的输入不是 `document_processor` 的原始直接返回值，而是 **backend 在 session 维度聚合后的标准化结果**。也就是说，进入这一层前，backend 需要先把标准化内容和业务标识补齐，不直接接收原始 `pdf/docx` 文件对象。

主链路是：

```text
backend 聚合后的 documents + task_spec
  -> 独立输入适配文件完成输入校验与协议适配
  -> file_extraction_agent.processor.extract(...)
  -> task spec 加载 + GraphInput 组装
  -> broad extraction
  -> broad output 校验与标准化
  -> field resolution
  -> ExtractionResult
```

展开后可以理解成：

```text
调用方先把 backend 聚合后的 session 输入交给独立输入适配文件，例如 input_adapter.py
  -> input_adapter.py 负责 session 级输入校验、协议适配，并产出内部可消费的已校验输入
  -> processor.extract(...) 消费已校验输入，负责 task spec 加载，不再负责顶层输入校验或原始 payload 协议兜底
  -> impl/normalization.py 把已校验输入和 task spec 整理成符合 schemas.py 约束的 GraphInput
  -> impl/graph.py 从 GraphInput 开始驱动两阶段流程
  -> impl/broad_extraction.py 生成每个字段的候选、证据、局部状态
  -> impl/validation.py 对 broad output 做字段级校验、归一化和缺失/歧义标记
  -> impl/resolution.py 针对每个目标字段读取全局 broad output，必要时做一次定向 extra lookup，再输出 resolved / failed
  -> processor.extract(...) 汇总成 ExtractionResult 返回给上层
```

## 当前目录设计

建议目录保持下面这个结构：

```text
file_extraction_agent/
├── __init__.py
├── input_adapter.py
├── processor.py
├── schemas.py
├── extractor_client.py
├── model_client_config.json
├── task_specs/
│   └── *.json
├── impl/
│   ├── graph.py
│   ├── state.py
│   ├── prompts.py
│   ├── normalization.py
│   ├── validation.py
│   ├── broad_extraction.py
│   └── resolution.py
└── docs/
    ├── DESIGN.md
    └── DEVLOG.md
```

各层职责如下：

- `input_adapter.py`
  独立负责外部输入进入 `file_extraction_agent` 之前的第一层处理：校验 session 级 payload、做协议适配，并把原始 payload 收敛成内部可消费的已校验输入。这一层必须单开文件，不应混进 `processor.py`、`graph.py` 或 route。
- `processor.py`
  对外统一入口，消费外部已经校验好的输入，负责 task spec 加载、调用 normalization 组装 `GraphInput`、再调用 graph，并返回最终结果。
- `schemas.py`
  定义数据契约，包括 session 级 `GraphInput`、文档级 `NormalizedDocument`、broad extraction / resolution / result aggregation 的结构化对象。
- `extractor_client.py`
  负责构造抽取执行客户端：先从环境变量读取 `BASE_URL`、`OPENAI_API_KEY`、`MODEL` 这些连接信息，再结合 `model_client_config.json` 里的结构化输出策略，返回真正可调用的结构化输出执行器。
- `model_client_config.json`
  保存模型客户端策略配置，例如优先走 `json_schema`、直接走 `tool_call`，还是按 fallback 顺序自动回退，以及 `temperature` 之类的请求参数。
- `task_specs/*.json`
  保存固定 schema、字段类型、关键字段标记、局部校验规则、cross-field hints、lookup hints。
- `impl/graph.py`
  只负责编排节点流转，不直接定义对外 API。
- `impl/state.py`
  定义流程内部执行态，只给 graph、broad extraction 和 resolution 这些节点共享。
- `impl/prompts.py`
  定义 broad extraction 和 field resolution 两阶段的指令文本组装逻辑，是内部执行策略，不作为外部注入点暴露。
- `impl/normalization.py`
  接收 `input_adapter.py` 已经整理好的中间输入和 `processor.py` 提供的 task spec，继续做进入 graph 前的内部归一化，产出 `schemas.py` 中定义的 `GraphInput`；它不是第一层外部 payload 校验入口。
- `impl/validation.py`
  做候选清洗、字段类型归一化、局部规则校验和状态归类。
- `impl/broad_extraction.py`
  调用字段抽取执行器生成字段级候选集合。
- `impl/resolution.py`
  按字段逐个定案，吸收全局字段输出，必要时执行一次定向补查询。

## 为什么 `state.py`、`prompts.py` 和 `normalization.py` 放在 `impl/`

当前设计下，`state.py` 不是模块级公共契约，而是流程内部执行态。它主要由：

- `impl/graph.py`
- `impl/broad_extraction.py`
- `impl/resolution.py`

这些内部节点共同读写。`processor.py` 不需要对外暴露 state，也不应该让调用方感知内部状态结构，因此把它放在 `impl/` 更符合语义。

`prompts.py` 也属于内部执行策略，而不是外部扩展接口。它虽然会根据 schema、字段规则和阶段动态拼装指令文本，但这种拼装是模块内部行为，不建议让调用方直接传 `prompt_override` 一类自由文本，以免破坏抽取行为稳定性、结构化输出约束和实验对比可复现性。

因此这两个文件都归入 `impl/`，表示：

- 它们服务于图执行细节
- 它们不是公开 API
- 调用方只和 `processor.extract(...)`、`schemas.py` 暴露的结果对象打交道

`normalization.py` 也保留在 `impl/`，但原因和 `state.py` 不完全一样。它虽然不属于 graph 内部节点，却仍然属于模块内部预处理逻辑，而不是对外公开契约。这里要特别和 `input_adapter.py`、`processor.py` 分开看：

- `input_adapter.py` 负责第一层外部输入校验和协议适配
- `processor.py` 负责 task spec 加载和流程编排
- `impl/normalization.py` 负责把已经过第一层收敛的输入连同 task spec 一起整理成 `schemas.py` 里定义好的 `GraphInput`

这样 `graph.py` 从一开始就只处理标准化后的输入，而不用承担外部输入整形、缺字段兜底或协议适配。

## `extractor_client.py` 与 `model_client_config.json` 的分工

这一层现在故意把“连接配置”和“调用策略”拆开，而不是全部堆进环境变量。

可以按下面的 pipeline 理解：

```text
部署环境提供 BASE_URL / OPENAI_API_KEY / MODEL
  -> extractor_client 先检查这三个连接变量是否齐全；缺任一项就直接报配置错误
  -> 再读取 model_client_config.json，拿到 structured_output.strategy、fallback_order、request_options
  -> 用 BASE_URL / OPENAI_API_KEY / MODEL 创建 ChatOpenAI(base_url=..., api_key=..., model=..., ...)
  -> 如果 strategy=json_schema，就固定使用 json_schema 结构化输出
  -> 如果 strategy=tool_call，就改走 tool calling；内部映射成 LangChain 的 function_calling
  -> 如果 strategy=auto，就按 fallback_order 先试 json_schema，再在兼容接口不支持时退到 tool_call
  -> broad extraction 和 field resolution 只收到统一的结构化 runnable，不需要关心底层用了哪种协议
```

这样拆分的目的有两点：

- 环境变量只负责部署相关的差异，例如服务地址、密钥、默认模型名。
- `model_client_config.json` 只负责代码行为差异，例如结构化输出协议和回退顺序，便于随仓库一起版本管理。

## 两阶段执行设计

### 第一阶段：broad extraction

这一阶段的目标是让每个字段先产生“局部意见”，而不是直接拍板最终值。

输入：

- `GraphInput.documents`
- 固定 task spec / schema

处理过程：

```text
GraphInput.documents
  -> 选择适合放进抽取输入的 markdown / block 摘要
  -> 根据 task spec 展开所有目标字段
  -> 调用字段抽取执行器一次返回所有字段的 BroadExtractionOutput
  -> validation.py 清洗空候选、归一化证据位置、补局部状态和局部校验结果
```

输出对象至少要保留：

- `field_name`
- `candidate_values`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_validation`
- `local_notes`

其中 `evidence_refs` 应统一记录：

- `document_id`
- `page`
- `span`
- `block_id`

这样后续字段定案、复核和审计时，能追踪每条候选证据来自哪里。

### 第二阶段：field resolution

这一阶段不是把整份文档一次性融合出最终答案，而是 **针对单个目标字段逐个定案**。

输入：

- 当前目标字段的 broad extraction 输出
- 所有字段的 broad extraction 输出摘要
- 当前字段的 schema 约束和校验规则
- 归一化后的文档内容

处理过程：

```text
当前 target field
  -> 读取它自己的候选、证据、局部状态
  -> 同时读取其他字段输出作为 cross-field hints
  -> 判断能否直接 resolved
  -> 如果证据不足但仍有收敛空间，就做一次定向 extra lookup
  -> 基于补查询结果再次判断
  -> 输出 resolved 或 failed
```

这里的 extra lookup 不是整份文档重跑，而是围绕当前字段做一次定向再确认，例如：

- 重新筛选当前字段相关的 block
- 重新检查关键表达
- 对两个相近候选做语义区分

输出只针对当前字段，至少要包含：

- `field_name`
- `status`
- `final_value`
- `used_field_outputs`
- `extra_lookup_used`
- `reason` 或 `failure_reason`

## Graph 输入与内部状态

`impl/graph.py` 不建议接收大量松散参数，而是只接收一个已经由 `normalization.py` 组装好的图输入对象和一个抽取执行客户端：

```python
run_extraction_graph(graph_input, extractor_client) -> ExtractionResult
```

推荐把图入口固定成一个在 `schemas.py` 中定义的 `GraphInput` 类型，至少包含：

- `session_id`
- `documents`
- `task_spec`
- `run_config`
- `metadata`

其中：

- `session_id`
  是 backend 在 session 聚合后补齐的顶层业务标识，用来说明这批文档属于同一次抽取会话。
- `documents`
  是 backend 聚合后的多文档输入，每个文档至少带 `document_id`、`markdown`、`md_list`、`blocks`
- `task_spec`
  是当前任务的固定 schema 定义
- `run_config`
  是流程执行策略，例如是否允许 extra lookup、每字段最多 lookup 次数、是否保留详细 trace
- `metadata`
  是可选任务标签、session 信息或调试信息

`GraphInput` 属于流程入口前就确定好的数据契约，因此放在 `schemas.py`，供 `normalization.py` 负责组装，供 `graph.py` 负责消费。

对应地，`impl/state.py` 定义图内部中间态，例如：

- `graph_input`
- `broad_output`
- `resolved_fields`
- `current_field`
- `lookup_trace`
- `warnings`

也就是说：

- `GraphInput` 是图的入口静态输入
- `GraphState` 是图运行过程中的中间状态

## 结构化 Schema 设计

### broad extraction 输出

第一层结构化输出建议由 `BroadExtractionOutput` 控制，并以字段为中心组织。每个字段对应一个候选 bundle，至少包含：

- `field_name`
- `candidate_values`
- `evidence_texts`
- `evidence_refs`
- `local_status`
- `local_validation`
- `local_notes`

这里允许一个字段存在多个候选，不要求这一层定唯一值。

### field resolution 输出

第二层结构化输出建议由 `ResolvedFieldOutput` 控制，并且只允许两种结果：

- `resolved`
- `failed`

对应字段至少包含：

- `field_name`
- `status`
- `final_value`
- `used_field_outputs`
- `extra_lookup_used`
- `reason`
- `failure_reason`

第一版不依赖精细浮点置信度，可以先用离散风险或强弱等级辅助解释。

### 最终聚合输出

`processor.extract(...)` 最终返回 `ExtractionResult`，建议包含：

- `broad_output`
- `resolved_fields`
- `run_trace`

其中 `run_trace` 记录执行轮次、extra lookup 痕迹、warnings 和其他辅助审计信息。

## task spec 设计

`task_specs/*.json` 负责表达固定 schema，而不是把字段规则硬编码到指令文本里。

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

这样 broad extraction 和 resolution 两阶段都能围绕固定字段约束工作，而不是开放式抽任意信息。

## 与外层治理的关系

`file_extraction_agent` 的职责是把抽取结果变成 **可治理对象**，不直接做最终 route。

因此它必须把这些材料准备完整：

- 每个字段的候选
- 候选证据文本
- 证据位置
- 局部状态
- 局部校验结果
- 定案时参考了哪些其他字段
- 是否执行过 extra lookup
- 最终定案原因或失败原因

后续外层治理层再根据这些结果决定：

- `pass`
- `review`
- `reject`
- `fallback`

这种分层可以把“模型产出了什么”和“系统是否允许写库”拆开，避免把写库判断硬塞进抽取链路。

## 测试约束

这一层有行为变化，必须按 TDD 推进。建议至少补这些测试文件，并为每个测试文件同步维护 `tests/docs/` 下的一一对应说明文档：

- `tests/file_extraction_agent/test_schemas.py`
- `tests/file_extraction_agent/test_processor.py`
- `tests/file_extraction_agent/test_validation.py`
- `tests/file_extraction_agent/test_broad_extraction.py`
- `tests/file_extraction_agent/test_resolution.py`
- `tests/file_extraction_agent/test_integration.py`

重点固定这些行为：

- 输入归一化与 task spec 加载
- broad extraction 结构化输出解析
- 局部校验和候选清洗
- 按字段逐个 resolution
- extra lookup 最多一次且只针对当前字段
- 最终结果可追踪到候选、证据和使用过的字段输出

## 文档同步要求

实现落地时，除了代码和测试，还需要同步维护：

- 当前这份 `docs/DESIGN.md`
- 对应测试文件的一一对应测试文档

如果后续需要补 `docs/DEVLOG.md`，必须先向用户说明：

- 要更新哪个 `DEVLOG.md`
- 准备记录什么
- 会采用什么格式

在获得批准后才能编辑。
