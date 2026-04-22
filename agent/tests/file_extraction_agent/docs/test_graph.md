# `test_graph.py`

## 基本实现思路

`file_extraction_agent.impl.graph` 负责把内部节点串成一条稳定的执行链路。它接收已经组装好的 `GraphInput` 和 extractor client，然后按固定顺序驱动内部状态流转，最后把执行态汇总成 `ExtractionResult(result + trace)`。

可以把 graph 理解成下面的 pipeline：

```text
GraphInput + extractor_client
  -> build_graph_state(graph_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state)
  -> 读取 state.result_fields / state.trace_fields / state.warnings
  -> 组装 ExtractionResult(result + trace)
```

## 测什么

- graph 会先运行 broad extraction，再运行 resolution
- resolution 读取的是 broad extraction 写回后的同一个 `GraphState`
- graph 最终会从状态里汇总 `result.fields`、`trace.fields` 和 `warnings`

## 每个函数在干什么

`test_run_extraction_graph_runs_broad_extraction_then_resolution`

- 用 monkeypatch 替换 graph 内部调用的两个节点函数。
- 记录调用顺序，并让 broad extraction 先写入 `broad_output`。
- 确认 resolution 紧跟其后运行，而且拿到的是前一个节点写回的状态。
- 最后确认 graph 会把状态里的结果和 warning 放进 `ExtractionResult(result + trace)`。

`test_run_extraction_graph_returns_result_and_trace_from_final_state`

- 让假的 broad extraction 产出 evidence bundles。
- 保留真实的 resolution 实现。
- 确认 graph 最终返回的 `result.fields` 与 `trace.fields` 都来自执行完成后的状态。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_graph.py -q
```
