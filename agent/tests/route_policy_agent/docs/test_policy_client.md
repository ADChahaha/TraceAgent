# `test_policy_client.py`

## 基本实现思路

`policy_client` 是 route policy 阶段的小 LLM 结构化调用层：

```text
evaluate(...) 未传 policy_client
  -> build_policy_client(base_url, api_key, model, structured_output_strategy)
  -> 校验连接参数，缺少 base_url / api_key 时抛 RoutePolicyClientConfigError
  -> 创建 ChatOpenAI
  -> invoke(output_schema=RoutePolicyDecision, messages=...)
  -> 只接受 with_structured_output(...) 产出的结构化结果
  -> 返回严格结构化的 route 决策对象
```

## 测什么

- 未提供显式连接参数且环境变量缺失时，会明确指出缺少 `base_url` 和 `api_key`。
- 不要求用户显式传 `model`，因为实现提供默认小模型名。
- 结构化调用失败后，不会再调用裸 `model.invoke(...)` 解析 JSON 文本。

## 每个函数在干什么

`test_build_policy_client_requires_connection_params`

- 清空连接相关环境变量。
- 调用 `build_policy_client()`。
- 确认错误信息包含 `base_url` 和 `api_key`，不包含 `model`。

`test_policy_client_rejects_raw_json_content_when_structured_invoke_fails`

- 用假的 `ChatOpenAI` 模拟结构化 runnable 调用失败。
- 即使裸模型能返回 JSON 文本，也确认 route policy client 不解析非结构化回退结果。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/route_policy_agent/test_policy_client.py -q
```
