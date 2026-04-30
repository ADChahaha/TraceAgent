# `test_schemas.py`

## 基本实现思路

`service.route_policy_agent.schemas` 定义 route policy 阶段自己的输入输出契约：

```text
backend 传入 task_spec、field_outputs、refs_with_text、field_processes
  -> RoutePolicyInput 只接收这些 route 判断所需字段
  -> RouteFieldOutput 保留字段名、状态和值，不接收 trace 或额外风险标记
  -> RouteFieldProcess 只保留 broad / resolution 的 search 查询词、count 摘要和过程摘要
  -> RoutePolicyDecision 只允许模型返回 route 和 route_reason
  -> FieldRouteDecision / RoutePolicyResult 对外返回字段级 route
```

## 测什么

- route policy 输入不接收抽取 trace。
- route policy 输入可以消费 `type=list` 字段和数组字段值。
- route prompt 的默认 refs 预算为每字段 50 条，避免列表字段证据被过早裁剪。
- route policy 输入不接收 search 工具返回结果。
- route policy 模型输出不允许给出新的字段值。

## 每个函数在干什么

`test_route_policy_input_rejects_extraction_trace_payload`

- 构造带 `trace` 的输入。
- 确认 Pydantic 解析会拒绝这个额外字段。

`test_route_policy_input_accepts_list_field_output`

- 构造 `type=list` 的学术论文名称字段。
- 字段输出使用 `["论文 A", "论文 B"]` 数组。
- 同时传入 broad / resolution 的 `search_queries`、`counted_fields` 等过程摘要。
- 确认 route policy 阶段能接收 file extraction 已定案的 list 值和过程摘要，并使用默认 `max_refs_per_field=50`。

`test_route_policy_input_rejects_tool_result_in_field_processes`

- 在 `field_processes.broad_extraction` 里塞入 `tool_results`。
- 确认 schema 拒绝工具返回结果，只允许过程摘要进入 route policy。

`test_route_policy_decision_rejects_new_field_value_payload`

- 模拟小 LLM 输出 `suggested_value`。
- 确认结构化输出 schema 拒绝模型改写字段值。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/route_policy_agent/test_schemas.py -q
```
