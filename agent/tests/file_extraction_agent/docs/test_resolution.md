# `test_resolution.py`

## 基本实现思路

`file_extraction_agent.impl.resolution` 负责第二阶段字段定案。它读取上一阶段的 `BroadExtractionOutput`，按 `task_spec.fields` 的顺序逐字段收口：没有候选值就失败，候选去重后只剩一个值就定案，仍有多个不同候选就按冲突失败。`run_resolution(...)` 只负责把这套收口逻辑应用到 `GraphState`，并把结果写回 `state.resolved_fields`。

可以把这层理解成下面的 pipeline：

```text
GraphState(graph_input, broad_output)
  -> 读取 graph_input.task_spec.fields 作为最终输出顺序
  -> 从 broad_output.fields 建立 field_name 到字段候选的索引
  -> 对每个字段做候选去重
  -> 空候选输出 failed
  -> 单一候选输出 resolved(final_value=唯一值)
  -> 多个不同候选输出 failed(冲突)
  -> 把结果写回 state.resolved_fields
```

## 测什么

- resolution 会按 `task_spec.fields` 顺序输出最终字段
- broad output 缺失字段时，会补一个显式失败结果
- 重复候选值会先去重，再决定是否可以定案
- 多个不同候选值会收口成冲突失败
- `run_resolution(...)` 会把计算结果写回 `GraphState`

## 每个函数在干什么

`test_resolve_fields_uses_task_spec_order_and_fills_missing_outputs`

- 构造只返回一个字段候选的 broad output。
- 确认 resolution 会保留 `task_spec` 顺序，并为缺失字段补一个失败结果。

`test_resolve_fields_deduplicates_same_candidate_before_resolving`

- 给同一个字段提供多个相同候选值。
- 确认 resolution 会先去重，再把这个字段收口成 `resolved`。

`test_resolve_fields_marks_conflicting_candidates_as_failed`

- 给同一个字段提供两个不同候选值。
- 确认 resolution 不会随意挑一个，而是显式标记为冲突失败。

`test_run_resolution_reads_broad_output_and_writes_back_to_state`

- 先构造带 `broad_output` 的 `GraphState`。
- 调用 `run_resolution(...)` 后检查 `state.resolved_fields` 已经被写回，证明第二阶段节点可以直接接在 broad extraction 后面运行。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
