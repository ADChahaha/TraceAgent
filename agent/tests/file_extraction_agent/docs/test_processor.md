# `test_processor.py`

## 基本实现思路

`file_extraction_agent.processor` 是这个模块的对外总入口。它不再自己承担外部输入适配，也不再自己手写 broad extraction / resolution 编排，而是接住 session 级输入，转交给 `input_adapter.build_graph_input(...)` 组装 `GraphInput`，再准备好 `ExtractorClient`，最后把这两个对象交给 `impl/graph.py` 返回 `ExtractionResult`。

这层当前按下面的 pipeline 理解：

```text
调用方传入 session_id + documents，再传 task_spec 或 task_spec_name
  -> processor.extract(...)
  -> 先把 session 级输入转交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责选择 task_spec，并组装 GraphInput
  -> 如果调用方没传 extractor_client，就先构造默认 ExtractorClient
  -> 调用 impl/graph.run_extraction_graph(graph_input, extractor_client)
  -> graph 内部继续驱动 broad extraction 和 resolution
  -> 返回 graph 汇总好的 ExtractionResult
```

## 测什么

- `processor` 会从 `session_id + documents + task_spec` 组装 pipeline 入口
- `processor` 会把 session 级输入委托给 `input_adapter`
- `processor` 会把 `GraphInput + ExtractorClient` 委托给 `graph`
- `processor` 支持通过 `task_spec_name` 从 `task_specs/*.json` 加载 schema
- `processor` 不再自己补字段结果，而是直接返回 graph 的结果
- 缺少 `task_spec` 和 `task_spec_name` 时会拒绝继续执行

## 每个函数在干什么

`test_extract_delegates_graph_input_building_to_input_adapter`

- 用假的 `build_graph_input(...)` 返回一份已经适配好的 `GraphInput`。
- 再用假的 `run_extraction_graph(...)` 接住 `GraphInput` 和 extractor client。
- 确认 `processor.extract(...)` 会把原始 session 参数先交给 `input_adapter`，再把适配后的 `GraphInput` 交给 graph。

`test_extract_delegates_execution_to_graph_with_built_client`

- 直接构造一份合法的 `session_id + documents + task_spec`。
- 用假的 `run_extraction_graph(...)` 返回一份完整的 `ExtractionResult`。
- 确认 `processor.extract(...)` 会把已经准备好的 extractor client 和 `GraphInput` 一起交给 graph，而不是自己直接调模型客户端。

`test_extract_loads_task_spec_from_task_spec_name`

- 在临时目录里写一份 `task_specs/invoice.json`。
- 只传 `task_spec_name`，不直接传 `task_spec`。
- 确认 `processor` 会先加载 task spec，再把组装好的 `GraphInput` 交给 graph。

`test_extract_returns_graph_result_without_reimplementing_field_fill`

- 让假的 `run_extraction_graph(...)` 直接返回两字段结果，其中一个失败。
- 确认 `processor` 不会自己重做字段补齐或重算，而是直接返回 graph 已经汇总好的结果。

`test_extract_rejects_missing_task_spec_and_task_spec_name`

- 故意只传 `session_id` 和 documents，不传任何 task spec 信息。
- 确认入口会拒绝继续执行，避免编排层在 schema 未确定的情况下进入抽取流程。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_processor.py -q
```
