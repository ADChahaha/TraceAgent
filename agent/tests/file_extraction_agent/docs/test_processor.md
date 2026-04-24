# `test_processor.py`

## 基本实现思路

`file_extraction_agent.processor` 是对外总入口。它负责：

```text
blocks + task_spec / task_spec_name
  -> input_adapter.build_graph_input(...)
  -> 组装内部 ExtractionInput
  -> 准备可 invoke 的 ExtractorClient
  -> 调用 impl/graph.run_extraction_graph(extraction_input, extractor_client)
  -> 返回 graph 汇总好的 ExtractionResult
```

它不自己做 broad / resolution，也不自己重算字段结果。

## 测什么

- `processor` 会先把 blocks 主输入委托给 `input_adapter`
- `processor` 会把内部 `ExtractionInput + ExtractorClient` 交给 graph
- 未传 extractor client 且缺少连接环境变量时会要求 `base_url` / `api_key`
- `structured_output_strategy` 会显式传给 extractor client builder
- `task_spec_name` 可以从 `task_specs/*.json` 加载 schema
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

`test_extract_passes_structured_output_strategy_to_client_builder`

- 不直接传 extractor client，只替换默认 builder。
- 确认 `processor` 会把连接参数和结构化输出策略一起传给 builder。

`test_extract_requires_explicit_connection_params_when_client_is_not_provided`

- 故意不传 extractor client，也不传连接参数，并依赖测试环境没有连接环境变量。
- 确认入口会要求 `base_url` / `api_key`，但不再要求 `model`，因为模型名已有默认值。

`test_extract_loads_task_spec_from_task_spec_name`

- 在临时目录写一份 task spec JSON。
- 只传 `task_spec_name`。
- 确认入口会先加载 task spec，再继续交给 graph。

`test_extract_returns_graph_result_without_reimplementing_field_fill`

- 让假的 graph 直接返回两字段结果。
- 确认 `processor` 不会自己再补字段或重算 trace。

`test_extract_rejects_missing_task_spec_and_task_spec_name`

- 故意只传 `blocks`。
- 确认入口会拒绝在 schema 未确定时继续执行。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_processor.py -q
```
