# `test_processor.py`

## 基本实现思路

`service.route_policy_agent.processor.evaluate(...)` 是 Python 业务入口，负责把外部输入串成字段级 route 判断：

```text
task_spec + field_outputs + refs_with_text
  -> RoutePolicyInput 解析
  -> input_validator.validate_route_policy_input(...) 做字段名和 refs 完整性校验
  -> mapper.build_field_policy_contexts(...) 合并单字段定义、输出和证据
  -> failed 的 critical/required 字段直接 reject，不调用模型
  -> resolved 字段用 prompts.build_route_policy_messages(...) 构造只含字段和 refs 的评价上下文
  -> policy_client.invoke(RoutePolicyDecision, messages) 得到 accept/review/reject
  -> 汇总 RoutePolicyResult(field_routes[])
```

## 测什么

- 模型判断 `accept` 时，字段 route 可自动放行。
- 模型判断证据不足时，字段进入 `review`。
- critical required 字段抽取失败时直接 `reject`，不调用小 LLM。
- 未显式传入 policy client 时，会把连接参数交给 client builder。

## 每个函数在干什么

`test_evaluate_accepts_resolved_field_when_policy_client_accepts`

- 用假的 policy client 返回 `accept`。
- 确认 processor 返回 `needs_review=False`，并且 prompt 中包含字段值和 refs 文本。

`test_evaluate_marks_resolved_field_for_review_when_evidence_is_insufficient`

- 用假的 policy client 返回 `review`。
- 确认 processor 保留模型给出的证据不足原因，并标记需要人工检查。

`test_evaluate_rejects_failed_critical_required_field_without_model_call`

- 构造一个 failed 且 critical required 的字段。
- 确认 processor 直接返回 `reject`，不会调用模型。

`test_evaluate_builds_policy_client_when_not_provided`

- 不传 policy client，替换 builder。
- 确认 base_url、api_key、model 和结构化输出策略会被传入 builder。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/route_policy_agent/test_processor.py -q
```
