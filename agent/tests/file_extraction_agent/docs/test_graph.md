# `test_graph.py`

## 基本实现思路

`file_extraction_agent.impl.graph` 负责把内部节点串成一条稳定的执行链路。它不处理外部输入适配，也不直接定义对外 HTTP 或 session 协议；它接收已经组装好的 `GraphInput` 和一个 extractor client，然后按固定顺序驱动内部状态流转，最后把执行态汇总成 `ExtractionResult`。

可以把 graph 理解成下面的 pipeline：

```text
GraphInput + extractor_client
  -> build_graph_state(graph_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state)
  -> 读取 state.broad_output / state.resolved_fields / state.warnings
  -> 组装 ExtractionResult
```

## 测什么

- graph 会先运行 broad extraction，再运行 resolution
- resolution 读取的是 broad extraction 写回后的同一个 `GraphState`
- graph 最终会从状态里汇总 `broad_output`、`resolved_fields` 和 `warnings`

## 每个函数在干什么

`test_run_extraction_graph_runs_broad_extraction_then_resolution`

- 用 monkeypatch 替换掉 graph 内部调用的两个节点函数。
- 记录调用顺序，并让 broad extraction 先写入 `broad_output`。
- 确认 resolution 紧跟其后运行，而且拿到的是前一个节点写回的状态。
- 最后确认 graph 会把状态里的 warning 带进 `ExtractionResult.run_trace`。

`test_run_extraction_graph_returns_resolved_fields_from_final_state`

- 让假的 broad extraction 产出一个可被 resolution 直接收口的 broad output。
- 保留真实的 resolution 实现。
- 确认 graph 最终返回的 `resolved_fields` 来自执行完成后的状态，而不是中途拼装的临时值。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_graph.py -q
```
