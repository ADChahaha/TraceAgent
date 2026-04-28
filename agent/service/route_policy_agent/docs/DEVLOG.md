# Route Policy Agent Devlog

last updated: 2026-04-28 12:33:11

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
