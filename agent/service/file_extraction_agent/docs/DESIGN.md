# File Extraction Agent Design

这份文档面向开发者，说明 `service.file_extraction_agent` 的目标结构、模块边界和函数职责。它处理的是 **backend 已经聚合并标准化后的 blocks**，负责把这些 blocks 转成字段级候选证据、字段最终定案和可追踪 trace。

## 目标

`service.file_extraction_agent` 不负责原始文件解析、写库、人工审核或 route policy。它只做一件事：

```text
backend 聚合后的 blocks + task_spec
  -> 外层输入适配和 blocks 契约校验
  -> broad 为各字段召回候选证据
  -> resolution 基于候选证据做字段定案
  -> 返回 ExtractionResult(result + trace)
```

当前设计有四个关键约束：

- `blocks` 入口校验放在外层适配层，进入 `impl/` 后默认 blocks 已满足契约。
- `broad` 和 `resolution` 是两个阶段目录，不再用扁平 `broad_extraction.py` / `resolution.py` 承载全部逻辑。
- 不保留独立 `validation` 阶段，也不把它改名成 `rules.py` 或 `constraints.py` 继续存在。
- tool 数量保持少而明确，不做动态 registry；runner 直接把当前阶段允许的工具注入给模型。

## 当前代码结构

```text
service/file_extraction_agent/
├── __init__.py
├── processor.py
├── input_adapter.py
├── block_contract.py
├── extractor_client.py
├── schemas.py
├── impl/
│   ├── __init__.py
│   ├── graph.py
│   ├── state.py
│   ├── schemas.py
│   ├── broad/
│   │   ├── __init__.py
│   │   ├── runner.py
│   │   └── prompts.py
│   ├── resolution/
│   │   ├── __init__.py
│   │   ├── runner.py
│   │   └── prompts.py
│   └── tools/
│       ├── __init__.py
│       ├── search.py
│       └── candidates.py
└── docs/
    ├── API.md
    ├── DESIGN.md
    └── DEVLOG.md
```

当前实现已经按这个结构落地。后续如果继续调整阶段目录、工具边界或 trace 语义，需要先按 TDD 修改对应测试，再同步更新本文档。

## 主处理链路

整体流程固定为：

```text
外部调用参数 blocks + task_spec + run_options + metadata
  -> processor.extract(...)
  -> input_adapter.build_graph_input(...)
  -> block_contract.validate_blocks_contract(...)
  -> impl/schemas.py::ExtractionInput
  -> graph.run_extraction_graph(...)
  -> state.build_graph_state(...)
  -> broad.runner.run_broad_stage(...)
  -> resolution.runner.run_resolution_stage(...)
  -> graph.map_state_to_result(...)
  -> schemas.py::ExtractionResult
```

可以按下面方式理解每一层：

1. `processor.py` 是对外 Python 入口，负责接请求参数、建模型客户端、调用内部 graph。
2. `input_adapter.py` 负责把外部参数变成内部 `ExtractionInput`。
3. `block_contract.py` 负责 blocks 的入口契约校验。
4. `impl/graph.py` 只做阶段编排和最终结果映射。
5. `impl/broad/` 只做候选证据召回，不输出最终字段值。
6. `impl/resolution/` 只做字段最终定案。
7. `impl/tools/` 提供 grep 搜索和候选池读写，工具本身不做定案。

## 对外入口

### `processor.py`

#### `extract(...)`

对外统一业务入口。

处理步骤：

```text
调用方传入 blocks、task_spec、run_options、metadata 和可选模型连接参数
  -> 调用 input_adapter.build_graph_input(...) 组装 ExtractionInput
  -> 如果调用方没有传 extractor_client 或阶段客户端，则调用 extractor_client.build_extractor_client(...)
  -> 如果传了 broad_model / resolution_model，则分别构造阶段客户端
  -> 调用 graph.run_extraction_graph(graph_input, extractor_client, stage clients)
  -> 返回 schemas.py::ExtractionResult
```

职责边界：

- 负责连接外部调用和内部 graph。
- 负责选择或创建模型调用客户端。
- 不做 blocks 逐项校验。
- 不直接执行 broad、resolution 或 tool。
- 不访问数据库或 backend storage。

失败行为：

- 外部输入不满足契约时，允许由 `input_adapter.py` 或 `block_contract.py` 抛出 `ValueError`。
- 内部 broad / resolution 执行失败时，由 `graph.run_extraction_graph(...)` 收口成 failed `ExtractionResult`。

### `input_adapter.py`

#### `build_graph_input(blocks, task_spec, markdown=None, md_list=None, run_options=None, metadata=None)`

把外部调用参数归一化成内部图输入对象。

处理步骤：

```text
外部调用参数
  -> 检查 task_spec 是否存在
  -> 调用 block_contract.validate_blocks_contract(blocks)
  -> 用 Pydantic 归一化 blocks 和 task_spec
  -> 缺省 run_options 时填充 RunOptions 默认值
  -> 保留 markdown、md_list 和 metadata
  -> 返回 impl.schemas.ExtractionInput
```

职责边界：

- 负责协议适配和内部输入对象组装。
- 负责调用 blocks 契约校验。
- 不启动模型调用。
- 不做候选召回。
- 不做字段定案。

失败行为：

- `task_spec` 缺失时抛 `ValueError("task_spec is required")`。
- blocks 契约失败时透传 `validate_blocks_contract(...)` 的 `ValueError`。
- Pydantic 归一化失败时透传校验异常。

### `block_contract.py`

#### `validate_blocks_contract(blocks)`

校验外部传入的 blocks 是否满足 file extraction 内部流程需要的最小契约。

处理步骤：

```text
blocks
  -> 检查 blocks 是可遍历的非空列表
  -> 检查每个 block 有稳定 block_id
  -> 检查 block_id 在本次输入内唯一
  -> 检查 document_id、kind、text 等 trace 所需字段可用，page_no 有值时会进入最终 trace
  -> 检查 table block 至少能被转换成行级文本
  -> 校验通过后返回 None
```

职责边界：

- 这是外层输入契约校验。
- 进入 `impl/` 后，内部代码默认 blocks 已合法，不再维护 `impl/block_ids.py`。
- 不生成 fallback block id。
- 不从 `meta_info` 猜测 block id。

失败行为：

- 任一 block 缺少 `block_id` 时抛 `ValueError`。
- 出现重复 `block_id` 时抛 `ValueError`。
- 缺少 trace 必需字段时抛 `ValueError`。

### `extractor_client.py`

#### `build_extractor_client(base_url=None, api_key=None, model=None, structured_output_strategy="tool_call")`

创建结构化输出模型调用器。

处理步骤：

```text
显式模型参数 + 环境变量
  -> 合并 base_url、api_key、model
  -> model 缺省时使用代码默认模型
  -> 校验 structured_output_strategy 只能是 tool_call
  -> 把 tool_call 映射成 LangChain 的 function_calling
  -> 返回 ExtractorClient
```

职责边界：

- 只解决“如何调用模型并拿到结构化结果”。
- 不理解 broad 或 resolution 的业务语义。
- 不拼装 prompt。
- 不编排 graph。

#### `ExtractorClient.invoke(messages, output_schema, tools=None)`

按指定 schema 调用模型。

处理步骤：

```text
messages + output_schema + 可选 tools
  -> 用 LangChain function_calling 构造结构化 runnable
  -> 调用底层模型并要求返回匹配 output_schema 的工具调用参数
  -> 解析成 Pydantic 结构化结果
  -> 返回结构化对象
```

职责边界：

- `tools` 由 runner 直接传入，不通过动态 registry 获取。
- 模型调用失败、结构化输出失败或超时，抛出异常，由 graph 统一收口。

## 外部稳定契约

### `schemas.py`

`schemas.py` 只定义对外稳定契约，不暴露内部 broad / resolution 的阶段对象。

建议继续承载：

- `FieldDefinition`
- `TaskSpec`
- `RunOptions`
- `NormalizedBoundingBox`
- `NormalizedBlock`
- `FieldEvidenceRef`
- `ExtractionResult`
- `ExtractionResult.result.fields[]`
- `ExtractionResult.trace.fields[]`
- `TraceAction`

`RunOptions` 中和本设计直接相关的选项应保持清晰：

- `max_prompt_blocks`：限制 broad 初始 prompt 可展示的 block 摘要数量。
- `max_prompt_block_chars`：限制单个 block 摘要长度。
- `max_resolution_candidates`：限制 resolution prompt 中候选证据数量。
- `max_broad_iterations`：作为每字段 broad 预算，runner 会乘以字段数得到共享 broad loop 最大动作轮次。
- `max_resolution_iterations`：作为每字段 resolution 预算，runner 会乘以字段数得到共享 resolution loop 最大动作轮次。
- `keep_detailed_trace`：是否保留更详细内部调试信息。

当前 grep 工具不使用 `top_k`。搜索返回多少，由确定性 grep 命中结果决定；如果后续需要限制最大返回数量，应使用明确的 `max_grep_results` 之类配置，不把它命名为 `top_k`。

## 内部流程契约

### `impl/schemas.py`

#### `ExtractionInput`

内部 graph 入口对象。

字段建议：

- `blocks`
- `task_spec`
- `markdown`
- `md_list`
- `options`
- `metadata`

进入 `ExtractionInput` 的 blocks 已经由 `block_contract.py` 校验过。

#### `SearchResult`

grep 搜索返回给模型的最小结果对象。

字段：

- `ref`
- `text`

其中：

```text
text paragraph ref = "{block_id}:p:{paragraph_id}"
table row ref      = "{block_id}:r:{row_id}"
```

`ref` 是模型可见、可追踪、可直接写入候选池的来源定位。系统不再引入 `match_id`。

#### `Candidate`

已经被模型选入候选池的证据对象。

字段建议：

- `candidate_id`
- `field_name`
- `source_stage`
- `ref`
- `text`
- `reason`

其中：

- `source_stage="broad"` 表示 broad 初次召回的候选。
- `source_stage="resolution"` 表示 resolution 二次搜索补充的候选。

#### `FieldDecision`

resolution 产出的字段最终定案对象。

字段建议：

- `field_name`
- `status`
- `value`
- `candidate_ids`
- `related_fields`
- `reason`
- `failure_reason`

#### `ToolActionRecord`

系统可证明发生过的动作记录。

字段建议：

- `field_name`
- `stage`
- `action_type`
- `message`
- `refs`
- `candidate_ids`
- `metadata`

action 类型至少包括：

- `search_grep`
- `add_broad_candidate`
- `add_resolution_candidate`
- `get_candidate_bundle`
- `finish_broad`
- `final_decision`
- `model_call_error`

## 内部状态

### `impl/state.py`

#### `GraphState`

保存一次 extraction run 内部执行态。

字段建议：

- `graph_input`
- `blocks_by_id`
- `paragraph_index`
- `table_row_index`
- `candidates`
- `broad_finishes`
- `field_decisions`
- `actions`
- `warnings`

`paragraph_index` 和 `table_row_index` 是 ref 的内部回查表：

```text
paragraph_index["block_12:p:p3"]
  -> block_id
  -> document_id
  -> page_no
  -> paragraph_id
  -> text

table_row_index["block_18:r:r5"]
  -> block_id
  -> document_id
  -> page_no
  -> row_id
  -> text
```

模型只看到 `ref` 和 `text`。最终 trace 需要 `document_id / page_no / block_id / locator` 时，由 graph 从这些 index 回查。

#### `build_graph_state(extraction_input)`

创建内部运行态。

处理步骤：

```text
ExtractionInput
  -> 建立 blocks_by_id
  -> 从 text 类 block 构建 paragraph_index
  -> 从 table block 构建 table_row_index
  -> 初始化 candidates、broad_finishes、field_decisions、actions、warnings
  -> 返回 GraphState
```

职责边界：

- 只建立内部索引和运行态。
- 不重新校验 block_id 是否缺失或重复。
- 不调用模型。
- 不执行字段抽取。

#### `record_action(state, field_name, action)`

记录系统可证明动作。

处理步骤：

```text
field_name + ToolActionRecord
  -> 追加到 state.actions[field_name]
  -> 保持动作顺序
```

职责边界：

- 只记录动作，不改变候选池或字段结果。
- 候选写入由 `tools/candidates.py` 完成。

## 图编排

### `impl/graph.py`

#### `run_extraction_graph(graph_input, extractor_client, broad_extractor_client=None, resolution_extractor_client=None)`

内部执行总入口。

处理步骤：

```text
ExtractionInput + 共享 ExtractorClient 或 broad/resolution 阶段客户端
  -> build_graph_state(graph_input)
  -> broad.runner.run_broad_stage(state, broad_client)
  -> resolution.runner.run_resolution_stage(state, resolution_client)
  -> map_state_to_result(state)
  -> ExtractionResult
```

客户端选择规则：

- 如果传了 `broad_extractor_client`，broad 阶段优先使用它。
- 如果传了 `resolution_extractor_client`，resolution 阶段优先使用它。
- 没有阶段客户端时，两个阶段复用 `extractor_client`。

失败收口：

```text
broad 或 resolution 抛异常
  -> 捕获异常
  -> 只给第一个未完成字段写 model_call_error 或流程错误 action
  -> build_failed_result(state, error)
  -> 返回 status="failed" 的 ExtractionResult
```

职责边界：

- 只编排阶段和映射结果。
- 不直接拼 prompt。
- 不直接做 grep。
- 不直接写候选池。

#### `map_state_to_result(state)`

把内部状态映射成外部 `ExtractionResult`。

处理步骤：

```text
GraphState
  -> 读取 state.field_decisions
  -> 生成只包含 field_name/status/value 的 result.fields[]
  -> 通过 candidate_id -> ref -> paragraph/table index 回查证据定位
  -> 生成 trace.fields[].evidence
  -> 复制 actions、related_fields、reason、failure_reason 到 trace.fields[]
  -> 返回 completed ExtractionResult
```

职责边界：

- 对外只暴露稳定 result / trace 语义。
- `result` 是纯业务结果，不重复放证据、动作或 prompt 调试信息。
- `trace` 是审计和治理层使用的证据链，保存候选证据、工具动作、定案原因和失败原因。
- 不暴露内部 prompt、raw model response 或链路私有对象。

#### `build_failed_result(state, error)`

把中途失败收口成可追踪的失败结果。

处理步骤：

```text
GraphState + error
  -> broad 失败时用 state.broad_finishes 判断已完成 broad 字段
  -> resolution 失败时用 state.field_decisions 判断已完成定案字段
  -> 未完成字段补 status=failed
  -> 只给第一个未完成字段写 model_call_error action
  -> trace.metadata 写 failure_stage、error_type、error_message、completed_field_names、pending_field_names
  -> 返回 failed ExtractionResult
```

## Broad 阶段

`broad` 的职责是字段级候选证据召回。它不输出最终字段值。

### `impl/broad/runner.py`

#### `run_broad_stage(state, extractor_client)`

运行一个共享 broad agent loop，直到所有字段都有 `finish_broad`。

处理步骤：

```text
GraphState
  -> 读取 task_spec.fields，计算 pending_fields
  -> build_broad_messages(state) 把所有字段、已完成字段和全字段候选池放入 prompt
  -> 直接注入 search_grep、add_broad_candidate、copy_field_candidates
  -> 调用 extractor_client.invoke(...) 获取 BroadAction
  -> 校验 action.field_name 必须属于 task_spec.fields
  -> search_grep：按 action.field_name 同时检索正文段落和表格行
  -> add_broad_candidate：把 refs 写入 action.field_name 对应候选池
  -> 如果 add_broad_candidate 收到不存在的 ref，记录 tool_error 并把错误作为下一轮 tool_result 返回给模型修正
  -> copy_field_candidates：把 source_field_name 的候选复制到 action.field_name，返回不含正文的复制摘要
  -> finish_broad：校验后写入 state.broad_finishes[action.field_name]
  -> 所有字段都有 finish_broad 后返回 GraphState
```

职责边界：

- 负责 broad 阶段整体调度。
- 不做字段最终定案。
- 不调用 resolution 工具。
- 不按字段启动独立模型 loop；字段之间的候选可以在同一阶段上下文里互相参考。

`run_broad_loop_for_field(...)` 只作为旧内部调用兼容包装存在；新实现不再依赖它编排单字段循环。

broad 可用动作：

- `search_grep(field_name, query)`
- `add_broad_candidate(field_name, refs, reason)`
- `copy_field_candidates(field_name, source_field_name, reason)`
- `finish_broad(field_name, status, reason)`

`finish_broad` 是 broad 的唯一正常出口，但它不是单独 tool 文件。runner 直接解析模型的 terminal action。

约束：

- `status=enough_evidence` 时，目标字段候选池必须非空。
- broad 只能把搜索结果加入候选池，不能输出字段最终值。
- 如果超过共享最大轮次仍有字段未 `finish_broad`，抛出包含 pending fields 的流程错误。

### `impl/broad/prompts.py`

#### `build_broad_messages(state)`

构造 broad prompt。

输入来源：

- 所有字段定义及字段 `lookup_hints` / `cross_field_hints`。
- `pending_fields` 和已完成 `finish_broad` 摘要。
- task 名称和必要 metadata。
- 可搜索内容的概要说明。
- 全字段已有候选摘要。
- 上一轮工具结果。

输出：

- 模型消息列表。

prompt 必须表达清楚：

- broad 只负责找候选证据。
- `search_grep` 会同时搜索正文 paragraph 和表格行。
- broad 不暴露 `count_field_candidates`；数量字段应在 resolution 阶段基于候选池统计。
- broad 可用 `copy_field_candidates` 在 state 内复制字段候选，工具结果不返回来源候选正文。
- payload 必须注入 `tool_contract`，说明每个 action 的用途、入参、返回和约束。
- `search_grep.query` 固定使用 `term1 OR term2 OR term3`，多个短关键词只能用大写 `OR` 连接。
- 候选引用使用 `ref`。
- 每个字段正常结束都必须返回 `finish_broad` action。

#### `format_broad_tool_result(result)`

把 broad 工具结果压缩成下一轮模型输入。

处理步骤：

```text
SearchResult[]、Candidate[]、复制摘要或 tool_error
  -> 只保留 ref/candidate_id 和 text
  -> copy_field_candidates 只返回 copied_candidate_count 和 copied_candidate_ids
  -> tool_error 只返回工具名、字段名、错误信息和模型修正提示
  -> 不暴露 block metadata、page_no、bbox 等内部定位细节
  -> 返回模型可读消息片段
```

## Resolution 阶段

`resolution` 的职责是字段最终定案。它默认读取 broad 候选池；如果候选不足，可以用同样的 grep 工具做二次补证，再通过 resolution 专用候选写入动作加入候选池。

### `impl/resolution/runner.py`

#### `run_resolution_stage(state, extractor_client)`

运行一个共享 resolution agent loop，直到所有字段都有 `final_decision`。

处理步骤：

```text
GraphState
  -> 读取 task_spec.fields，计算 pending_fields
  -> build_resolution_messages(state) 把所有字段、候选池和已完成定案放入 prompt
  -> 直接注入 get_candidate_bundle、search_grep、add_resolution_candidate、count_field_candidates
  -> 调用 extractor_client.invoke(...) 获取 FieldResolutionAction
  -> 校验 action.field_name 必须属于 task_spec.fields
  -> get_candidate_bundle：读取 action.field_name 对应候选池摘要
  -> search_grep：按 action.field_name 同时检索正文段落和表格行
  -> add_resolution_candidate：把 refs 或 values 写入 action.field_name 对应候选池
  -> 如果 add_resolution_candidate 收到不存在的 ref，记录 tool_error 并把错误作为下一轮 tool_result 返回给模型修正
  -> count_field_candidates：统计 action.field_name 当前候选数量并记录 trace，返回 number 给模型
  -> final_decision：校验 candidate_id 后写入 state.field_decisions[action.field_name]
  -> 所有字段都有 FieldDecision 后返回 GraphState
```

职责边界：

- 负责字段定案阶段调度。
- 不重新执行 broad。
- 不做 route policy。
- 不写数据库。
- 不按字段启动独立模型 loop；数量字段可以在同一阶段参考列表字段的候选数量。

`run_resolution_loop_for_field(...)` 只作为旧内部调用兼容包装存在；新实现不再依赖它编排单字段循环。

resolution 可用动作：

- `get_candidate_bundle(field_name)`
- `search_grep(field_name, query)`
- `add_resolution_candidate(field_name, refs | values, reason)`
- `count_field_candidates(field_name)`
- `final_decision(field_name, status, value, candidate_ids, related_fields, reason)`

`final_decision` 是 resolution 的唯一正常出口，但它不是独立 tool 文件。runner 直接解析模型的 terminal action。

约束：

- `status=resolved` 时必须引用至少一个 `candidate_id`。
- `candidate_id` 必须来自 `final_decision.field_name` 对应的候选池。
- resolution 可以把二次搜索命中的 ref 追加为候选，但不能直接引用未入候选池的 ref 做最终决策。
- 如果超过最大轮次仍未 `final_decision`，抛出流程错误。

#### `build_field_decision_from_final_action(state, field, action)`

把模型的 terminal action 转成内部 `FieldDecision`。

处理步骤：

```text
final_decision action
  -> 校验 target field 与当前 field 一致
  -> status=resolved 时校验 candidate_ids 非空
  -> 校验 candidate_ids 都存在于 state.candidates[field_name]
  -> 用 candidate_id 回查 ref 和 text
  -> 组装 FieldDecision
  -> 记录 final_decision action
  -> 返回 FieldDecision
```

职责边界：

- 只做 terminal action 的结构约束和证据回查。
- 不恢复独立 `validation` 层。
- 不执行额外业务规则覆盖。

### `impl/resolution/prompts.py`

#### `build_resolution_messages(state)`

构造 resolution prompt。

输入来源：

- 所有字段定义。
- `pending_fields`。
- 全字段候选池摘要。
- 已完成字段结果摘要。
- 上一轮工具结果。
- 必要运行选项。

输出：

- 模型消息列表。

prompt 必须表达清楚：

- resolution 负责最终字段定案。
- 若候选不足，可以先 grep 并调用 `add_resolution_candidate`。
- `count_field_candidates` 只统计指定字段当前候选数量，返回 number；模型若要把数字作为目标字段证据，必须再调用 `add_resolution_candidate(values=[...])`。
- payload 必须注入 `tool_contract`，说明每个 action 的用途、入参、返回和约束。
- `search_grep.query` 固定使用 `term1 OR term2 OR term3`，多个短关键词只能用大写 `OR` 连接。
- 每个字段最终必须通过 `final_decision` action 退出。
- `final_decision` 只能引用对应字段候选池里的 `candidate_id`，不能直接引用 grep 返回的 ref。

#### `format_resolution_tool_result(result)`

把 resolution 工具结果压缩成下一轮模型输入。

处理步骤：

```text
候选读取结果、grep 结果、候选写入结果、tool_error 或 number
  -> 候选读取/写入只保留 candidate_id/ref/text
  -> tool_error 只返回工具名、字段名、错误信息和模型修正提示
  -> 不暴露 block metadata、page_no、bbox 等内部定位细节
  -> 返回模型可读消息片段
```

## Tools

tool 文件只保留确定性能力，不承载阶段编排。

### `impl/tools/search.py`

#### `search_grep(state, field_name, query)`

在正文段落和表格行中做一次统一确定性 grep。

处理步骤：

```text
query
  -> 只按大写 OR 拆成 query_terms
  -> 在 paragraph_index 中按文档原始顺序查找任一关键词命中
  -> 在 table_row_index 中按文档原始顺序和 row 顺序查找任一关键词命中
  -> paragraph 命中返回完整 paragraph，table 命中返回当前 table row
  -> 每条结果只返回 SearchResult(ref, text)
  -> 记录 search_grep action，并在 metadata.query_terms 中保留拆词结果
```

返回给模型：

```text
[
  {"ref": "block_12:p:p3", "text": "命中所在完整段落"},
  {"ref": "block_18:r:r5", "text": "列名1=值1 | 列名2=值2"}
]
```

约束：

- 每次 search 都同时查正文和表格，不让模型在 text/table 两个搜索工具之间反复试错。
- paragraph 是文本语义段落，不等同于 block；table row 是行级证据，不返回整张表。
- query 中的 `A OR B` 表示任一关键词命中即可返回；只支持大写 `OR` 作为多词分隔。
- 不支持中文“或”、逗号、顿号、斜杠或自然语言句子作为多词分隔。
- 不使用 `top_k`。
- 不做语义排序。
- 不返回 `document_id`、`page_no`、bbox 等追踪字段给模型。

#### `search_text_grep(...)` / `search_table_rows_grep(...)`

保留为兼容旧测试或内部直接调用的窄入口。broad / resolution runner 不再把它们暴露给模型；模型侧统一使用 `search_grep`。
- 不做语义排序。
- 不返回 `document_id`、`page_no`、bbox 等追踪字段给模型。

### `impl/tools/candidates.py`

#### `add_broad_candidate(state, field_name, refs, reason)`

broad 专用候选写入函数。

处理步骤：

```text
refs + reason
  -> 校验每个 ref 存在于 paragraph_index 或 table_row_index
  -> 如果同一字段已存在同 ref 候选，复用已有 candidate_id 或跳过去重
  -> 为新 ref 生成 candidate_id
  -> 写入 Candidate(source_stage="broad")
  -> 记录 add_broad_candidate action
  -> 返回 candidate_id 和 text
```

职责边界：

- 只把 broad grep 结果写入候选池。
- 不做字段最终定案。
- 不修改已完成字段结果。

#### `add_resolution_candidate(state, field_name, refs=None, values=None, reason)`

resolution 专用候选写入函数。

处理步骤：

```text
refs / values + reason
  -> 对 refs 校验每个 ref 存在于 paragraph_index 或 table_row_index
  -> 对 values 生成 value:{field_name}:vN 这类内部 ref
  -> 如果同一字段已存在同 ref 或同 value 候选，复用已有 candidate_id 或跳过去重
  -> 为新 ref/value 生成 candidate_id
  -> 写入 Candidate(source_stage="resolution")
  -> 记录 add_resolution_candidate action
  -> 返回 candidate_id 和 text
```

职责边界：

- 只服务 resolution 二次补证。
- 可把 `count_field_candidates` 返回的数字通过 `values` 写成目标字段候选。
- 和 broad 写入同一个候选池，但 `source_stage` 不同。
- 不直接产出 `FieldDecision`。

#### `get_candidate_bundle(state, field_name)`

读取字段候选池。

处理步骤：

```text
field_name
  -> 读取 state.candidates[field_name]
  -> 按 candidate_id 稳定顺序返回候选摘要
  -> 记录 get_candidate_bundle action
```

返回给模型：

```text
[
  {"candidate_id": "c1", "text": "候选证据文本"},
  {"candidate_id": "c2", "text": "候选证据文本"}
]
```

职责边界：

- 只读候选池。
- 不新增候选。
- 不改变候选状态。
- 不做最终字段判断。

#### `count_field_candidates(state, field_name, stage, reason=None)`

统计字段候选池当前数量。

处理步骤：

```text
field_name + stage
  -> 读取 len(state.candidates[field_name])
  -> 记录 count_field_candidates action，metadata.count 保留数量
  -> 返回 number
```

职责边界：

- 只读候选池数量。
- 不返回候选正文或 ref 列表。
- 不新增候选。
- 不直接产出字段值。

#### `copy_field_candidates(state, source_field_name, target_field_name, stage, reason)`

把一个字段已有候选复制到另一个字段。

处理步骤：

```text
source_field_name + target_field_name + reason
  -> 读取 state.candidates[source_field_name]
  -> 将每个候选的 ref/text 复制为 target_field_name 的当前阶段候选
  -> 已存在同 ref 的目标候选直接复用
  -> 记录 copy_field_candidates action，metadata.source_field_name 和 metadata.copied_candidate_count 保留过程摘要
  -> 返回 copied_candidate_count 和 copied_candidate_ids，不返回候选正文或 ref 列表
```

职责边界：

- 只在 state 内复制候选，避免把来源候选正文作为工具结果再次塞回 prompt。
- 不读取新证据。
- 不直接产出字段值。

## Ref 与 Candidate ID

本设计不使用 `match_id`。

原因是搜索结果本身已经可以用来源定位表达：

```text
text paragraph ref = "{block_id}:p:{paragraph_id}"
table row ref      = "{block_id}:r:{row_id}"
```

`ref` 的职责：

- 作为 grep 结果的稳定定位。
- 作为 add candidate 的输入。
- 支持系统回查真实 block、paragraph 或 table row。

`candidate_id` 的职责：

- 表示某个 ref 已被模型明确加入候选池。
- 作为多轮 resolution 的工作记忆。
- 作为 `final_decision` 的唯一证据引用。

因此：

```text
grep 返回 ref
  -> add_broad_candidate / add_resolution_candidate 生成 candidate_id
  -> get_candidate_bundle 返回 candidate_id
  -> final_decision 只能引用 candidate_id
  -> graph 用 candidate_id -> ref -> index 回查 trace
```

## 删除和迁移规则

目标结构落地时，旧文件按下面方向迁移：

```text
impl/broad_extraction.py
  -> impl/broad/runner.py
  -> impl/broad/prompts.py

impl/resolution.py
  -> impl/resolution/runner.py
  -> impl/resolution/prompts.py

impl/prompts.py
  -> impl/broad/prompts.py
  -> impl/resolution/prompts.py

impl/tools.py
  -> impl/tools/search.py
  -> impl/tools/candidates.py

impl/block_ids.py
  -> block_contract.py

impl/validation.py
  -> 删除
```

不要新增下面这些替代物：

- `impl/registry.py`
- `impl/tools/registry.py`
- `impl/tools/exits.py`
- `impl/resolution/rules.py`
- `impl/resolution/constraints.py`
- `normalize_candidate_refs(...)`

其中：

- exit 是 runner 解析的 terminal action，不单独成工具文件。
- ref 校验是 `add_broad_candidate(...)` / `add_resolution_candidate(...)` 的内部逻辑，不暴露成独立函数。
- 字段最终结构约束放在 `build_field_decision_from_final_action(...)` 中做最小检查，不恢复独立 validation 阶段。

## 测试约束

后续实现这份结构时必须按 TDD 推进。

建议测试文件继续和实现边界对应：

- `tests/file_extraction_agent/test_input_adapter.py`
- `tests/file_extraction_agent/test_processor.py`
- `tests/file_extraction_agent/test_graph.py`
- `tests/file_extraction_agent/test_state.py`
- `tests/file_extraction_agent/test_broad_extraction.py`
- `tests/file_extraction_agent/test_resolution.py`
- `tests/file_extraction_agent/test_tools.py`

新增或修改测试时，必须同步维护 `tests/file_extraction_agent/docs/` 下的一一对应说明文档。

重点行为：

- `block_contract.py` 在外层校验 block_id 必填唯一。
- `impl/` 内部不再承担 blocks 入口校验。
- text grep 返回 paragraph 级 `ref/text`。
- table grep 只返回单行 `ref/text`。
- grep 不使用 `top_k`。
- broad 只能通过 `add_broad_candidate` 写候选，并通过 `finish_broad` 退出。
- resolution 可通过 `add_resolution_candidate` 补候选，并通过 `final_decision` 退出。
- `final_decision` 只能引用 `candidate_id`，不能直接引用 grep 返回的 ref。
- `validation.py` 删除后，不以 `rules.py` 或 `constraints.py` 形式复活。

## 文档同步要求

当目录结构、主链路、函数职责或 trace 语义发生实现变更时，需要同步更新本设计文档。

如果后续需要更新 `docs/DEVLOG.md`，必须先向用户说明：

- 要更新哪个 `DEVLOG.md`
- 准备记录什么
- 采用什么格式

获得批准后才能编辑。
