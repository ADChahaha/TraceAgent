# `test_state.py`

## 基本实现思路

`file_extraction_agent.impl.state` 负责承载图运行时的内部中间态。它不是外部输入契约，也不是最终输出结果，而是把 `GraphInput` 运行过程中逐步产生的 broad output、最终字段结果和必要 warning 统一收进一个状态对象里，供 `graph.py`、`broad_extraction.py`、`resolution.py` 共享。

可以按下面的 pipeline 理解：

```text
build_graph_state(graph_input)
  -> 先接住已经由 input_adapter 组装好的 GraphInput
  -> 初始化 graph_input / broad_output / resolved_fields / warnings
  -> 运行过程中由 graph 节点不断写入中间结果
  -> 最终给 resolution 汇总提供同一个状态容器
```

这个测试文件的目标就是把这个状态容器的默认值和可承载的进度数据钉住，避免后续 graph、broad extraction 或 resolution 落地时把内部状态改散。

## 测什么

- `build_graph_state(...)` 会基于已有 `GraphInput` 生成一份空的执行态
- `GraphState` 会保留已经准备好的 broad output、resolved fields 和 warnings

## 每个函数在干什么

`test_build_graph_state_initializes_empty_execution_state`

- 构造一份最小合法的 `GraphInput`。
- 调用 `build_graph_state(...)`。
- 确认状态对象会把 `GraphInput` 原样收下，并把执行中的中间字段初始化为空值。

`test_graph_state_accepts_prepared_progress_payloads`

- 手工构造一份已经有部分执行进度的 `GraphState`。
- 确认它能承载 broad output、已定案字段和 warnings，方便 graph 节点之间接力。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_state.py -q
```
