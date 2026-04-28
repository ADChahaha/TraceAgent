# Route Policy Agent Design

这份文档记录 `service.route_policy_agent` 的设计。它是 `agent service` 下独立于 `service.file_extraction_agent` 的第三个处理阶段，负责像第三方评价者一样，根据任务、字段输出和 refs 中的证据文本判断字段结果应当 `accept / review / reject`。

## 目标与边界

`service.route_policy_agent` 的目标不是重新抽取字段，而是判断 `service.file_extraction_agent` 已经产出的字段结果能否进入后端治理流程的下一步。

主链路是：

```text
TaskSpec + field_outputs + refs_with_text
  -> route_policy_agent
  -> 按 field_name 合并字段定义、字段输出和 refs 证据文本
  -> 小 LLM 独立判断 accept / review / reject
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
- 不消费额外风险标记，例如 `used_global_lookup`、`used_validation_rule`、`model_call_error`。

这层和 `service.file_extraction_agent` 的区别是：

```text
service.file_extraction_agent
  -> 回答字段值是什么、refs 证据在哪里

service.route_policy_agent
  -> 只根据字段输出和 refs 中的证据文本回答这个字段结果应 accept、review 还是 reject
```

## 推荐结构

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
    ├── API.md
    └── DESIGN.md
```

对应 HTTP route 建议放在：

```text
agent/routes/route_policy_agent.py
```

对外路径建议为：

```text
POST /v1/route-policy-agent/evaluate
```

## 输入

`service.route_policy_agent` 的输入应当只包含做 route 判断所需的信息。第一版把它设计成第三方评价者：除任务/字段定义和待评估字段输出外，只看 `refs` 中携带的证据文本和来源位置。

- `task_spec`
  - 字段定义、是否 required、是否 critical、是否 allow_missing、字段类型、业务提示。
- `field_outputs`
  - 字段最终值和字段状态。
- `refs_with_text`
  - 每条 ref 必须包含证据文本和来源位置，例如 `document_id`、`page`、`block_id`、`span`、`text`。
- 可选 `policy_options`
  - 小 LLM 模型配置和调用预算。

这里的 `refs` 不能只是定位信息。如果 ref 只有 `document_id/page/span/block_id`，它只能说明证据位置，不能让 route policy 判断字段值是否真的被证据支持。第一版要求使用 `refs_with_text`：每条 ref 自带证据文本，route policy 不再读取抽取过程、trace actions、抽取 reason 或额外风险标记。

推荐输入 pipeline：

```text
backend 传入 task_description / task_spec
  -> 传入待评估 field_outputs
  -> 传入每个字段对应的 refs_with_text
  -> service.route_policy_agent.schemas 做 Pydantic 解析
  -> input_validator 校验字段名、字段输出和 refs 文本完整性
  -> mapper 按 field_name 合并 FieldDefinition、FieldOutput、refs_with_text
  -> prompts 构造只包含字段定义、字段输出和 refs 文本的 route prompt
  -> policy_client 调小 LLM 独立判断 accept / review / reject
  -> 返回 RoutePolicyResult
```

## 输入校验

`input_validator.py` 负责跨对象校验，避免把协议一致性检查混进 mapper 或 prompt 构造。它只检查 route policy 需要的输入是否完整，不补全文本、不读取原文、不从 trace 中推断 refs。

推荐校验 pipeline：

```text
RoutePolicyInput(task_spec + field_outputs + refs_with_text)
  -> 校验 task_spec.fields 中 field_name 唯一
  -> 校验每个 field_output.field_name 都能在 task_spec.fields 中找到
  -> 校验每个待评估字段都有对应 refs_with_text
  -> 校验每条 ref 都有非空 text 和至少一个来源位置 document_id/page/block_id/span
  -> 校验请求中没有抽取推理过程、trace actions 或额外风险标记字段
  -> 返回 ValidatedPolicyInput，供 mapper 合并字段上下文
```

校验失败时应返回明确错误或 failed 结果，错误信息需要指出具体字段名和缺失项，例如缺少 `refs_with_text.text`、字段名不在 `task_spec.fields` 中，或 ref 只有定位信息但没有证据文本。

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

字段级 route 判断应当只围绕字段输出和 refs 文本展开：

```text
FieldDefinition + FieldOutput + refs_with_text
  -> input_validator 校验输入完整性和字段对应关系
  -> mapper 合并字段定义、字段值和该字段 refs
  -> prompts 构造不包含抽取推理过程的评价上下文
  -> policy_client.invoke(RoutePolicyDecision)
  -> FieldRouteDecision
```

### 1. 合并字段上下文

mapper 接收已经通过 `input_validator` 的输入，只按 `field_name` 对齐字段定义、字段输出和 refs：

```text
ValidatedPolicyInput
  -> 按 field_name 找到 FieldDefinition
  -> 按 field_name 找到 FieldOutput
  -> 按 field_name 找到该字段 refs_with_text
  -> 合并成 FieldPolicyContext
```

### 2. 小 LLM 给出 route 决策

小 LLM 只接收字段级评价上下文，不接收整篇文档，也不接收抽取 agent 的推理过程：

```text
任务描述和字段定义
  -> 字段值和字段状态
  -> refs 中的证据文本
  -> refs 的来源位置
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
- route policy 需要作为第三方评价者，只看字段输出和 refs 证据文本来判断是否放行。
- route policy 后续可以独立做消融实验，例如不同小 LLM、不同 prompt 或不同 refs 裁剪策略。
- 把 route policy 独立出来，可以避免 `service.file_extraction_agent` 同时承担抽取、证据留痕和业务放行判断。

## 测试重点

后续实现时需要按 TDD 补测试，并为测试文件同步维护 `tests/docs/` 说明文档。

建议覆盖：

- resolved 且证据充分的非关键字段可以 `accept`。
- resolved 但 refs 文本无法充分支持字段值时进入 `review`。
- critical required 字段 failed 时必须 `reject`。
- 输入校验能拒绝未知字段名、缺少 refs、ref 没有 text 或只有定位信息的请求。
- 小 LLM 不允许产生新的字段值。
- 输入缺少字段输出或 refs 文本时返回 failed 或明确 warning。

## 原型范围

第一版只做字段级 route 判断，不做：

- 多轮 route 对话。
- 重新抽取字段。
- 人工审核界面。
- 写库或 audit。
- 读取 backend 数据库。
- 直接读取原始文件或全文 blocks。
