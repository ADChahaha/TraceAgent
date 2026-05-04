# Route Policy Agent Design

这份文档记录 `service.route_policy_agent` 的设计。它是 `agent service` 下独立于 `service.file_extraction_agent` 的第三个处理阶段，负责像第三方评价者一样，根据任务、字段输出、refs 中的证据文本和两阶段过程摘要判断字段结果应当 `accept / review / reject`。

## 目标与边界

`service.route_policy_agent` 的目标不是重新抽取字段，而是判断 `service.file_extraction_agent` 已经产出的字段结果能否进入后端治理流程的下一步。

主链路是：

```text
TaskSpec + field_outputs + refs_with_text + field_processes
  -> route_policy_agent
  -> 按 field_name 合并字段定义、字段输出、refs 证据文本和抽取过程摘要
  -> required 且 allow_missing=false 的字段如果没有填，直接 route=review
  -> 小 LLM 结合最终证据和抽取路径判断 accept / review / reject
  -> RoutePolicyResult(field_routes[])
  -> backend 保存 field_routes 并驱动 review / audit
```

边界：

- 不接收 PDF / DOCX 原始文件。
- 不读取完整原文，也不重新跑 `service.document_processor`。
- 不重新抽取字段值，不修改 `ExtractionResult.result`。
- 不直接访问 backend 数据库。
- 不写最终结果，不执行人工审核，不生成 audit。
- 只输出字段级 route 决策和原因。
- 不读取抽取 agent 的完整 prompt、raw model response、chain-of-thought 或详细推理过程。
- 不读取 search 工具返回的候选正文、table row、cell、block_id 列表或其他工具结果。
- 只消费抽取过程的事实摘要：broad / resolution 阶段各自执行过哪些统一 `search_grep` 查询词、是否写入过候选、是否执行最终定案，以及阶段状态和失败原因。

这层和 `service.file_extraction_agent` 的区别是：

```text
service.file_extraction_agent
  -> 回答字段值是什么、refs 证据在哪里

service.route_policy_agent
  -> 根据字段输出、refs 证据文本和抽取过程摘要回答这个字段结果应 accept、review 还是 reject
```

## 当前结构

```text
service/route_policy_agent/
├── __init__.py
├── processor.py
├── schemas.py
├── input_validator.py
├── policy_client.py
├── impl/
│   ├── mapper.py
│   └── prompts.py
└── docs/
    ├── DESIGN.md
    └── DEVLOG.md
```

对应 HTTP route 放在：

```text
agent/routes/route_policy_agent.py
```

对外路径为：

```text
POST /v1/route-policy-agent/evaluate
```

## 输入

`service.route_policy_agent` 的输入应当只包含做 route 判断所需的信息。当前把它设计成第三方评价者：除任务/字段定义和待评估字段输出外，它看 `refs` 中携带的最终证据文本，也看 `file_extraction_agent` 的两阶段过程摘要，用来判断抽取路径是否充分。

- `task_spec`
  - 字段定义、是否 required、是否 critical、是否 allow_missing、字段类型、业务提示。
- `field_outputs`
  - 字段最终值和字段状态；`type=list` 字段的值应是字符串数组，route policy 只评价该数组是否被 refs 支持，不把它改写成字符串。
- `refs_with_text`
  - 每条 ref 必须包含证据文本和来源位置，例如 `document_id`、`page`、`block_id`、`span`、`text`。
- `field_processes`
  - 每个待评估字段必须有一条过程摘要，包含 `broad_extraction` 和 `field_resolution` 两段。
  - 两段中的 `search_queries` 只记录统一 search 工具发起过的查询词，例如 `学术论文 OR 论文题目 OR 作品类型`，不记录 `search_text` / `search_table_rows` 这类内部拆分。
  - 过程摘要可以包含候选写入数量、broad 结束原因、是否执行 `final_decision`、resolution 原因和失败原因。
  - 过程摘要不能包含 search 工具返回的正文、表格行、cell、block_id 列表或 action refs；最终证据文本仍只从 `refs_with_text` 读取。
- 可选 `policy_options`
  - route prompt 的 refs 数量和文本长度预算，`max_refs_per_field` 默认 50。

这里的 `refs` 不能只是定位信息。如果 ref 只有 `document_id/page/span/block_id`，它只能说明证据位置，不能让 route policy 判断字段值是否真的被证据支持。`refs_with_text` 仍是最终证据来源；`field_processes` 只说明 agent 搜索和定案路径是否合理，不替代证据文本。

对于派生字段，mapper 会按字段定义中的 `validation_rules.source_field` 或 `validation_rules.source_fields` 找到来源字段过程摘要，并在单字段 prompt 中额外放入 `related_field_processes`。例如 `academic_paper_count` 的 broad 可能只是复制 `academic_paper_names` 的候选，route policy 判断数量字段时必须能看到来源字段 broad 查过 `学术论文 OR 论文题目 OR 作品类型`。这里仍只传过程摘要，不传 search 工具返回结果。

推荐输入 pipeline：

```text
backend 传入 task_description / task_spec
  -> 传入待评估 field_outputs
  -> 传入每个字段对应的 refs_with_text
  -> 从 field_traces.actions_json 提取每个字段的 broad / resolution 过程摘要
  -> 只保留 search_grep 查询词、候选写入数量、finish_broad 信息和 final_decision 是否执行
  -> service.route_policy_agent.schemas 做 Pydantic 解析
  -> input_validator 校验字段名、字段输出、refs 文本和 field_processes 是否完整
  -> mapper 按 field_name 合并 FieldDefinition、FieldOutput、refs_with_text、field_process
  -> 如果字段声明了 source_field/source_fields，mapper 附加来源字段的 related_field_processes
  -> deterministic rule 先把 required 且 allow_missing=false 的未填写字段 route=review
  -> prompts 构造只包含字段定义、字段输出、refs 文本、当前字段过程摘要和来源字段过程摘要的 route prompt
  -> policy_client 调小 LLM 独立判断 accept / review / reject
  -> 返回 RoutePolicyResult
```

## 输入校验

`input_validator.py` 负责跨对象校验，避免把协议一致性检查混进 mapper 或 prompt 构造。它只检查 route policy 需要的输入是否完整，不补全文本、不读取原文、不从 trace 中推断 refs 或 search query。

推荐校验 pipeline：

```text
RoutePolicyInput(task_spec + field_outputs + refs_with_text + field_processes)
  -> 校验 task_spec.fields 中 field_name 唯一
  -> 校验每个 field_output.field_name 都能在 task_spec.fields 中找到
  -> 校验每个待评估字段都有对应 refs_with_text
  -> 校验每条 ref 都有非空 text 和至少一个来源位置 document_id/page/block_id/span
  -> 校验每个待评估字段都有对应 field_processes
  -> 校验 field_processes 只包含两阶段过程摘要，不包含工具返回结果或 action refs
  -> 返回 ValidatedPolicyInput，供 mapper 合并字段上下文
```

校验失败时应返回明确错误或 failed 结果，错误信息需要指出具体字段名和缺失项，例如缺少 `refs_with_text.text`、字段名不在 `task_spec.fields` 中、ref 只有定位信息但没有证据文本，或缺少 `field_processes`。

## 输出

输出是字段级 route 决策：

```text
RoutePolicyResult
  -> status
  -> field_routes[]
       -> field_name
       -> route
       -> route_reason
       -> needs_review
  -> warnings
  -> metadata
```

`route` 只允许：

```text
accept
review
reject
```

语义：

- `accept`：字段结果可信，可以由 backend 自动生成字段提交记录。
- `review`：字段结果可能可用，但需要人工检查或修改后再通过。
- `reject`：关键字段不可用，或 refs 文本不足以支持字段值，不允许进入最终提交。

## Route 判断流程

字段级 route 判断先执行 deterministic rule，再围绕字段输出、refs 文本和抽取过程摘要展开：

```text
FieldDefinition + FieldOutput + refs_with_text + field_process
  -> input_validator 校验输入完整性和字段对应关系
  -> mapper 合并字段定义、字段值、该字段 refs 和两阶段过程摘要
  -> required 且 allow_missing=false 的字段如果 failed、空字符串、空列表或缺少 field_output，直接 review
  -> prompts 构造不包含工具返回结果、不包含原始推理的评价上下文
  -> policy_client.invoke(RoutePolicyDecision)
  -> FieldRouteDecision
```

当前第一版对“必填但没填”的字段先做硬规则判断：如果字段是
`required` 且 `allow_missing=false`，并且出现以下情况之一，直接返回
`review`，避免让模型决定是否可以放行：

- `file_extraction_agent` 没有返回该字段的 `field_output`。
- 字段状态是 `failed`。
- 字段状态是 `resolved`，但值是空字符串、空列表、空对象或 `null`。

这条规则只负责把“必填没填”的字段送入人工复核或补录，不直接判
`reject`。`reject` 仍用于字段不可提交、关键证据不支持或其他业务上必须拒绝
的情况。

实际处理 pipeline 是：

```text
processor.evaluate(task_spec, field_outputs, refs_with_text, field_processes)
  -> RoutePolicyInput 解析并拒绝未知字段
  -> input_validator 校验字段名、refs 分组、ref.text、来源位置和 field_processes 分组
  -> mapper 按 field_name 合并 FieldDefinition、RouteFieldOutput、EvidenceTextRef[]、RouteFieldProcess
  -> 派生字段额外带上 source_field/source_fields 对应的 related_field_processes
  -> required + allow_missing=false 且没填的字段直接生成 FieldRouteDecision(route=review)
  -> resolved 字段由 prompts 构造只含字段定义、字段输出、refs 文本和过程摘要的 messages
  -> policy_client.invoke(RoutePolicyDecision, messages)
  -> 如果 task_spec 中还有 required + allow_missing=false 但完全缺席的字段，补一条 route=review
  -> 汇总 RoutePolicyResult(field_routes[])
```

`policy_client` 只接受 `with_structured_output(...)` 产出的结构化结果，不解析裸
`model.invoke(...)` JSON 文本。当前 route policy 固定只支持 `structured_output_strategy=tool_call`，客户端内部映射到 LangChain 的 `function_calling`；显式传入 `json_schema` 或 `auto` 会被拒绝，结构化调用失败时直接作为 route policy 模型调用失败向上抛出。

route policy 的模型名必须显式配置，不使用默认模型，也不读取通用 `MODEL`。配置入口保持为：

```text
HTTP 请求显式传入 model
  -> 否则读取 agent 进程环境变量 ROUTE_POLICY_MODEL
  -> 两者都没有时抛 RoutePolicyClientConfigError，HTTP 层返回 422
```

这样可以避免 route policy 隐式复用 broad / resolution 的抽取模型，让“抽取字段”和“治理判断”两个阶段的模型选择保持可解释。

### 1. 合并字段上下文

mapper 接收已经通过 `input_validator` 的输入，只按 `field_name` 对齐字段定义、字段输出和 refs：

```text
ValidatedPolicyInput
  -> 按 field_name 找到 FieldDefinition
  -> 按 field_name 找到 FieldOutput
  -> 按 field_name 找到该字段 refs_with_text
  -> 按 field_name 找到该字段 field_process
  -> 从 validation_rules.source_field/source_fields 找到相关来源字段 field_process
  -> 合并成 FieldPolicyContext
```

### 2. 小 LLM 给出 route 决策

小 LLM 只接收字段级评价上下文，不接收整篇文档，也不接收抽取 agent 的原始推理过程或工具返回结果：

```text
任务描述和字段定义
  -> 字段值和字段状态
  -> refs 中的证据文本
  -> refs 的来源位置
  -> broad_extraction.search_queries / candidate_action_count / counted_fields / finish_reason
  -> field_resolution.search_queries / candidate_action_count / counted_fields / final_decision_used / reason / failure_reason
  -> 派生字段的 related_field_processes，说明来源字段 broad/resolution 查过什么、写入过多少候选和如何定案
  -> 输出 route + reason
```

小 LLM 不允许输出新的字段值。如果它认为值需要修改，只能输出 `route=review`，由 backend 的人工审核流程处理。

## 与 Backend 的关系

`backend` 调用顺序建议是：

```text
POST /tasks
  -> agent /v1/document-processor/process
  -> agent /v1/file-extraction-agent/extract
  -> agent /v1/route-policy-agent/evaluate
  -> backend 保存 field_routes
  -> route=accept 时生成 field_commits
  -> route=review 时进入人工审核
  -> route=reject 时终止字段提交
```

`backend` 不做 LLM route 判断，只保存 `service.route_policy_agent` 的输出并驱动状态流转。`backend` 可以做必要的数据库完整性校验，但不重新解释字段证据。

## 与 `service.file_extraction_agent` 的关系

`service.file_extraction_agent` 应保持输出 `ExtractionResult(result + trace)` 的职责，不内置 route policy。

原因：

- 抽取和治理决策是两个不同问题。
- route policy 需要作为第三方评价者，只看字段输出、refs 证据文本和抽取过程摘要来判断是否放行。
- route policy 后续可以独立做消融实验，例如不同小 LLM、不同 prompt 或不同 refs 裁剪策略。
- 把 route policy 独立出来，可以避免 `service.file_extraction_agent` 同时承担抽取、证据留痕和业务放行判断。

## 测试重点

后续实现时需要按 TDD 补测试，并为测试文件同步维护 `tests/docs/` 说明文档。

建议覆盖：

- resolved 且证据充分的非关键字段可以 `accept`。
- resolved 但 refs 文本无法充分支持字段值时进入 `review`。
- resolved 且 refs 支持字段值，但 broad / resolution 搜索路径明显不足时进入 `review`。
- 派生字段 prompt 能看到来源字段的 search 查询词和过程摘要，例如数量字段能看到列表字段查过什么。
- required 且不允许缺失的字段 failed、空值或缺少 field_output 时必须 `review`，且不调用小 LLM。
- 输入校验能拒绝未知字段名、缺少 refs、ref 没有 text 或只有定位信息的请求。
- 小 LLM 不允许产生新的字段值。
- 输入缺少 refs 文本或 `field_processes` 时返回 failed 或明确 warning。

## 原型范围

第一版只做字段级 route 判断，不做：

- 多轮 route 对话。
- 重新抽取字段。
- 人工审核界面。
- 写库或 audit。
- 读取 backend 数据库。
- 直接读取原始文件或全文 blocks。
