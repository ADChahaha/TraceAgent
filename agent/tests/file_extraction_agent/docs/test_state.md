# `test_state.py`

## 基本实现思路

`file_extraction_agent.impl.state` 负责承载图运行时的内部中间态。

```text
build_graph_state(extraction_input)
  -> 接住已经由 input_adapter 组装好的 ExtractionInput
  -> 初始化 extraction_input / evidence_collection / field_decisions / warnings
  -> 运行过程中由 broad / resolution 节点不断写入中间结果
```

## 测什么

- `build_graph_state(...)` 会基于已有 `ExtractionInput` 生成一份空状态
- `GraphState` 会保留已经准备好的 `evidence_collection`、`field_decisions` 和 `warnings`

## 每个函数在干什么

`test_build_graph_state_initializes_empty_execution_state`

- 构造一份最小合法的 `ExtractionInput`。
- 确认状态对象会把它原样收下，并把内部执行字段初始化为空值。

`test_graph_state_accepts_prepared_progress_payloads`

- 手工构造一份已有执行进度的 `GraphState`。
- 确认它能承载 evidence、field decisions 和 warnings。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_state.py -q
```
