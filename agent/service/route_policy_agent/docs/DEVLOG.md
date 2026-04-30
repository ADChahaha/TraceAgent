# Route Policy Agent Devlog

last updated: 2026-04-30 20:42:20

## 2026-04-30 20:42:20

### 已完成工作

- route policy 输入正式消费 `field_processes`，每个字段包含 broad / resolution 两阶段过程摘要：search 查询词、候选写入数量、count 摘要、finish/final_decision 状态和失败原因。
- 对 `validation_rules.source_field/source_fields` 声明的派生字段，mapper 会把来源字段过程摘要注入为 `related_field_processes`。
- prompt system 文案明确解释 `field_process` 和 `related_field_processes` 的用途：只判断 agent 是否查过合理关键词、是否写入候选、是否计数和定案，不作为原文证据。
- route policy 的证据文本仍只来自 `refs_with_text.text`，不接收 search 工具返回正文、表格行、cell、block_id 列表或 raw trace。
- route policy 结构化输出策略固定为 `tool_call`，显式传入 `json_schema` 或 `auto` 会被拒绝。
- `policy_options.max_refs_per_field` 默认从 8 调整为 50，避免列表字段 route 判断时过早裁剪证据。

### 当前进展

- `academic_paper_count` route prompt 能看到来源字段 `academic_paper_names` 的 broad 查询词，例如 `学术论文 OR 论文题目 OR 论文替代`。
- 真实前端 E2E 中 route policy 对 `academic_paper_count` 和 `academic_paper_names` 均返回 `accept`，并在 count 字段原因中明确提到 `related_field_processes`。

### 验证

- `conda run -n agent-gate python -m pytest tests/route_policy_agent -q`，结果 `19 passed`。
- `conda run -n agent-gate python -m pytest tests/file_extraction_agent tests/route_policy_agent tests/routes/test_route_policy_agent_route.py -q`，结果 `90 passed`。

### 下一步

- 后续可以继续围绕 route policy prompt 做小模型消融，比较只看当前字段过程和同时看来源字段过程的 review/accept 差异。

## 2026-04-28 14:19:45

### 已完成工作

- 按当前决策明确 route policy 的 `structured_output_strategy=auto` 语义：保留 `json_schema -> tool_call` 的结构化协议重试。
- 保持 route policy 不解析裸 `model.invoke(...)` 响应，只接受 `with_structured_output(...)` 产出的结构化 route 决策。
- 更新 `route_policy_agent/docs/DESIGN.md`，说明 route policy 阶段为了兼容小模型 provider 会重试结构化协议。
- 补充 policy client 测试和测试说明文档，固定 `json_schema` 失败时会尝试 LangChain `function_calling`。

### 当前进展

- route policy 的模型调用边界已明确：可以在结构化协议之间重试，但不读取 raw model response。
- 完整 agent 测试已通过：`126 passed, 2 warnings`。

### 遇到的问题

- review 中把 route policy 的 tool call 重试也列为偏差；经确认这一路径需要保留，因此改为同步设计和测试，而不是删除重试行为。

### 下一步

- 后续如果要进一步区分 route policy 的协议不支持和 invoke 失败，需要先明确是否仍要求小模型场景下跨协议重试。

## 2026-04-28 13:32:31

### 已完成工作

- 移除 `policy_client.py` 中结构化调用失败后的裸 `model.invoke(...)` JSON / tool call 回退。
- 补充 policy client 回归测试，固定 route policy 只接受 `with_structured_output(...)` 产出的结构化结果。

### 当前进展

- route policy 的模型调用边界已与设计一致：只消费字段定义、字段输出和 `refs_with_text`，只接受结构化 route 决策。
- 真实文明寝室 PDF 三段端到端验证中，route policy 对 `building_name`、`civilized_dormitory_rooms`、`civilized_dormitory_count` 均返回 `accept`。

### 遇到的问题

- 旧实现会在结构化输出失败后解析裸 JSON 文本，和“不读取 raw model response”的设计口径不一致。

### 下一步

- 后续接真实 backend 调用链时，继续让 backend 只传 `field_outputs + refs_with_text`，不把抽取 trace actions 或 raw 模型响应传入 route policy。

## 2026-04-28 12:33:11

### 已完成工作

- 实现 `route_policy_agent` 的 `schemas.py`、`input_validator.py`、`policy_client.py`、`processor.py`、`impl/mapper.py` 和 `impl/prompts.py`。
- 新增 `POST /v1/route-policy-agent/evaluate`，并在 FastAPI app 中挂载 route policy router。
- 新增 `route_policy_agent` 单元测试、HTTP route 测试，以及对应 `tests/docs/` 测试说明文档。
- 同步更新 `agent/docs/DESIGN.md` 和 `route_policy_agent/docs/DESIGN.md`，记录当前结构、HTTP 出口和实际处理 pipeline。

### 当前进展

- 新增 route policy agent 已通过目标测试。
- 已验证现有 routes 测试未被破坏。

### 下一步

- 后续可接入真实 backend 调用链和真实小 LLM 配置做端到端验证。

## 2026-04-28 11:17:55

### 已完成工作

- 更新 `route_policy_agent/docs/DESIGN.md`，在推荐结构和处理链路中新增 `input_validator.py`。
- 明确 `input_validator.py` 负责跨对象输入校验：字段名、字段输出、`refs_with_text`、ref 文本和来源位置完整性。
- 明确输入校验不补全文本、不读取原文、不从 trace 推断 refs，并拒绝抽取推理过程、trace actions 或额外风险标记字段。

### 当前进展

- `route_policy_agent` 仍处于设计文档阶段，尚未实现代码、HTTP route 或测试。
- 第一版链路已调整为 `schemas -> input_validator -> mapper -> prompts -> policy_client`。

### 下一步

- 按 TDD 实现 `schemas.py`、`input_validator.py`、`processor.py`、`policy_client.py`、`impl/mapper.py` 和 `impl/prompts.py`。
- 新增 `routes/route_policy_agent.py` 暴露 `POST /v1/route-policy-agent/evaluate`。
- 为新增测试文件同步补齐 `tests/docs/` 下的一一对应说明文档。

## 2026-04-28 11:15:10

### 已完成工作

- 更新 `route_policy_agent/docs/DESIGN.md`，将第一版 route policy agent 明确为第三方评价者。
- 将输入边界收敛为 `task_spec / field_outputs / refs_with_text`，要求每条 ref 携带证据文本和来源位置。
- 明确不读取抽取 agent 的完整 prompt、raw model response、chain-of-thought、详细推理过程、trace actions 或额外风险标记。
- 将推荐实现链路调整为 `mapper -> prompts -> policy_client`，不再引入 `rules.py` 和风险特征硬约束流程。

### 当前进展

- `route_policy_agent` 仍处于设计文档阶段，尚未实现代码、HTTP route 或测试。
- 第一版接口方向已从消费 `ExtractionResult(result + trace)` 调整为消费字段输出和 `refs_with_text`。

### 下一步

- 按 TDD 实现 `schemas.py`、`processor.py`、`policy_client.py`、`impl/mapper.py` 和 `impl/prompts.py`。
- 新增 `routes/route_policy_agent.py` 暴露 `POST /v1/route-policy-agent/evaluate`。
- 为新增测试文件同步补齐 `tests/docs/` 下的一一对应说明文档。

## 2026-04-28 10:56:45

### 已完成工作

- 新增 `route_policy_agent/docs/DESIGN.md`，定义 route policy agent 的目标、边界、推荐结构、输入输出和判断流程。
- 明确 route policy agent 输入为 `TaskSpec + ExtractionResult(result + trace)`，不读取原始文件、不访问 backend 数据库、不重新抽取字段值。
- 明确 route 输出限定为 `accept / review / reject`，由小 LLM 给建议，rules 做风险特征提取和硬约束校正。

### 当前进展

- `route_policy_agent` 处于设计文档阶段，尚未实现代码、HTTP route 或测试。
- 模块边界已经和 `file_extraction_agent` 区分：抽取层负责字段值和 trace，route policy 层负责写库前处置判断。

### 下一步

- 按 TDD 实现 `schemas.py`、`processor.py`、`policy_client.py` 和 `impl/rules.py`。
- 新增 `routes/route_policy_agent.py` 暴露 `POST /v1/route-policy-agent/evaluate`。
- 为新增测试文件同步补齐 `tests/docs/` 下的一一对应说明文档。
