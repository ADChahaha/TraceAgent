# `test_route_policy_agent_route.py`

## 基本实现思路

`routes/route_policy_agent.py` 只做 HTTP 到业务入口的协议适配：

```text
HTTP POST /v1/route-policy-agent/evaluate
  -> FastAPI 用 route policy 的稳定 schema 解析 JSON
  -> route 层把 task_spec、field_outputs、refs_with_text、field_processes 和模型连接参数传给 processor.evaluate(...)
  -> structured_output_strategy 固定只允许 tool_call，并继续透传给业务入口
  -> processor 返回 RoutePolicyResult
  -> route 层原样返回字段级 route 决策
  -> 业务校验或连接配置错误转换成 HTTP 422
```

## 测什么

- HTTP route 会调用 `service.route_policy_agent.processor.evaluate(...)`。
- route 会把模型连接参数和 `tool_call` 结构化输出策略一并传给业务入口。
- route 不接收 `policy_options`，也不会把旧的 refs 裁剪参数传给业务入口。
- 业务入口抛出的输入校验错误会转换为 422。

## 每个函数在干什么

`test_route_policy_agent_route_calls_business_evaluator`

- 替换 processor 的 `evaluate(...)`。
- 通过 TestClient 请求 route。
- 确认 route 传入的字段定义、字段输出、refs 文本、field_processes search 查询词、连接参数和 `structured_output_strategy=tool_call` 正确。
- 确认业务入口不会收到 `policy_options`。

`test_route_policy_agent_route_rejects_policy_options_payload`

- 构造带旧 `policy_options` 字段的 HTTP 请求。
- 确认 FastAPI schema 在协议层返回 422，避免旧 refs 裁剪参数继续进入业务层。

`test_route_policy_agent_route_returns_422_for_business_validation_error`

- 让假的业务入口抛出 `ValueError`。
- 确认 HTTP 响应为 422，并保留业务错误信息。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/routes/test_route_policy_agent_route.py -q
```
