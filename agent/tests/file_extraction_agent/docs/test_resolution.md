# `test_resolution.py`

## 基本实现思路

`file_extraction_agent.impl.resolution` 负责第二阶段字段定案。当前先实现一个最小 deterministic 版本：它读取上一阶段的 `BroadExtractionOutput`，按 `task_spec.fields` 的顺序逐字段生成纯结果 `ResolvedFieldResult`，并同步生成字段级 `FieldTraceRecord`。

可以把这层理解成下面的 pipeline：

```text
GraphState(graph_input, broad_output)
  -> 读取 graph_input.task_spec.fields 作为最终输出顺序
  -> 从 broad_output.fields 建立 field_name 到 evidence bundle 的索引
  -> 有 evidence_texts 的字段先用第一条 evidence_text 作为占位 final_value
  -> 缺少 evidence bundle 或 evidence_texts 的字段输出 failed
  -> 把 result_fields 与 trace_fields 写回 GraphState
```

后续接入真正 resolution agent 时，可以替换定案逻辑，但仍应保持 `result` 与 `trace` 分离。

## 测什么

- resolution 会按 `task_spec.fields` 顺序输出最终字段
- broad output 缺失字段时，会补一个显式失败结果
- broad trace 与纯结果会分离保存
- `run_resolution(...)` 会把 result 与 trace 写回 `GraphState`

## 每个函数在干什么

`test_resolve_fields_uses_task_spec_order_and_fills_missing_outputs`

- 构造只返回一个字段 evidence bundle 的 broad output。
- 确认 resolution 会保留 `task_spec` 顺序，并为缺失字段补一个失败结果。

`test_resolve_fields_keeps_broad_trace_separate_from_result`

- 构造两个字段的 evidence bundle。
- 确认 `result_fields` 只保存纯业务结果，而 `trace_fields` 保留 broad 阶段的 block 与说明。

`test_run_resolution_reads_broad_output_and_writes_result_and_trace_to_state`

- 先构造带 `broad_output` 的 `GraphState`。
- 调用 `run_resolution(...)` 后检查 `state.result_fields` 与 `state.trace_fields` 已经被写回。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
