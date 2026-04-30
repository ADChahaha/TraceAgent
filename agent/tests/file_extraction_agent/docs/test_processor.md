# `test_processor.py`

## 基本实现思路

`service.file_extraction_agent.processor` 是对外总入口。它负责：

```text
blocks + 显式 task_spec
  -> input_adapter.build_graph_input(...)
  -> 校验 blocks 均带有上游传入的唯一 block_id
  -> 组装内部 ExtractionInput
  -> 准备共享 ExtractorClient，或按 broad_model / resolution_model 准备阶段客户端
  -> 调用 impl/graph.run_extraction_graph(extraction_input, extractor_client, stage clients)
  -> 返回 graph 汇总好的 ExtractionResult
```

它不自己做 broad / resolution，也不自己重算字段结果。

## 测什么

- `processor` 会先把 blocks 主输入委托给 `input_adapter`
- 直接入口的合法 blocks 必须携带显式 `block_id`
- `processor` 会把内部 `ExtractionInput + ExtractorClient` 交给 graph
- `processor` 支持直接传 broad / resolution 阶段客户端。
- `processor` 支持用 `broad_model` / `resolution_model` 构造不同阶段客户端。
- 未传 extractor client 且缺少连接环境变量时会要求 `base_url` / `api_key`
- `structured_output_strategy` 会以 `tool_call` 传给 extractor client builder
- 不显式传 `structured_output_strategy` 时，默认也会使用 `tool_call`
- 缺少显式 `task_spec` 时会被拒绝
- `processor` 直接返回 graph 的 `ExtractionResult`

## 每个函数在干什么

`test_extract_delegates_graph_input_building_to_input_adapter`

- 用假的 `build_graph_input(...)` 返回一份内部 `ExtractionInput`。
- 再用假的 graph 接住这个对象。
- 确认 `processor` 只负责组装和委托。

`test_extract_delegates_execution_to_graph_with_built_client`

- 直接传一份合法 blocks 输入。
- 用假的 graph 返回 `ExtractionResult`。
- 确认 `processor` 会把构造好的内部输入和 extractor client 一起交给 graph。

`test_extract_allows_distinct_stage_clients`

- 直接传入 broad / resolution 两个阶段客户端。
- 确认 `processor` 不再构造共享客户端，而是把两个阶段客户端交给 graph。

`test_extract_builds_distinct_stage_clients_when_stage_models_are_configured`

- 配置 `broad_model` 和 `resolution_model`。
- 确认 builder 分别用两个模型名构造阶段客户端，并保留相同连接参数和结构化输出策略。

`test_extract_passes_structured_output_strategy_to_client_builder`

- 不直接传 extractor client，只替换默认 builder。
- 确认 `processor` 会把连接参数和 `tool_call` 结构化输出策略一起传给 builder。

`test_extract_defaults_structured_output_strategy_to_tool_call`

- 不显式传 `structured_output_strategy`，只替换默认 builder。
- 确认 `processor` 默认把结构化输出策略固定为 `tool_call`。

`test_extract_requires_explicit_connection_params_when_client_is_not_provided`

- 故意不传 extractor client，也不传连接参数，并依赖测试环境没有连接环境变量。
- 确认入口会要求 `base_url` / `api_key`，但不再要求 `model`，因为模型名已有默认值。

`test_extract_returns_graph_result_without_reimplementing_field_fill`

- 让假的 graph 直接返回两字段结果。
- 确认 `processor` 不会自己再补字段或重算 trace。

`test_extract_rejects_missing_task_spec`

- 故意只传 `blocks`。
- 确认入口会拒绝在 schema 未确定时继续执行。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_processor.py -q
```
