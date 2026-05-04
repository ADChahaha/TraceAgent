# `test_schemas.py`

## 基本实现思路

`service.route_policy_agent.schemas` 定义 route policy 阶段自己的输入输出契约：

```text
backend 传入 task_spec、field_outputs、refs_with_text、field_processes
  -> RoutePolicyInput 只接收这些 route 判断所需字段
  -> RouteFieldOutput 保留字段名、状态和值，不接收 trace 或额外风险标记
  -> RouteFieldProcess 只保留 broad / resolution 的 search 查询词、count 摘要、过程摘要和轻量质量诊断
  -> RoutePolicyDecision 只允许模型返回 route 和 route_reason
  -> FieldRouteDecision / RoutePolicyResult 对外返回字段级 route
```

## 测什么

- route policy 输入不接收抽取 trace。
- route policy 输入可以消费 `type=list` 字段和数组字段值。
- route policy 输入可以消费 `table_audit/query_audit` 这类轻量工具观察摘要。
- route policy 输入拒绝质量诊断里夹带原始表格行、cell 值或工具结果。
- route policy 输入拒绝 `status` 这类提前下风险结论的诊断字段。
- route policy 输入不接收 `policy_options`，prompt 层不再有 refs 条数或文本长度裁剪参数。
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
- 确认 route policy 阶段能接收 file extraction 已定案的 list 值和过程摘要。

`test_route_policy_input_accepts_quality_diagnostics_summary`

- 构造 `query_audit.summary` 摘要，包含 source、table_id、query、quality_type 和 summary。
- 确认 schema 接收轻量工具观察摘要，且不需要 `status`。

`test_route_policy_input_rejects_diagnostic_status_payload`

- 构造仍带 `status` 的旧诊断输入。
- 确认 schema 拒绝这个额外字段，避免 route policy 继续依赖诊断状态硬判。

`test_route_policy_input_rejects_raw_rows_in_quality_diagnostics`

- 在 quality diagnostics 里塞入 `rows` 和 `row_values`。
- 确认 schema 拒绝原始表格行或 cell 值，避免 route policy 输入膨胀成工具返回结果。

`test_route_policy_input_rejects_policy_options_payload`

- 构造仍带 `policy_options` 的旧输入。
- 确认 Pydantic 解析会拒绝这个额外字段，避免 prompt 层重新出现静默裁剪参数。

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
