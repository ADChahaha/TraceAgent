# `test_graph.py`

## 基本实现思路

`file_extraction_agent.impl.graph` 负责串联内部节点，并把内部 `FieldDecision` 映射成对外 `ExtractionResult`。

```text
ExtractionInput + ExtractorClient
  -> build_graph_state(extraction_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state, extractor_client)
  -> 读取 state.field_decisions / state.warnings
  -> 映射成 ExtractionResult(result + trace)
```

## 测什么

- graph 会先跑 broad，再跑 resolution
- resolution 读取的是 broad 写回后的同一个状态对象
- graph 会把同一个 `extractor_client` 继续传给 resolution 阶段
- graph 最后会把内部 `FieldDecision` 映射成外部 `FieldResult` / `FieldTrace`

## 每个函数在干什么

`test_run_extraction_graph_runs_broad_extraction_then_resolution`

- 用 monkeypatch 替换 broad 和 resolution。
- 记录调用顺序，并让 broad 先写入 `evidence_collection`。
- 确认 resolution 紧跟其后运行，而且拿到的是同一个状态和同一个模型客户端。

`test_run_extraction_graph_maps_internal_decisions_to_external_result`

- 构造内部 evidence 和 decision。
- 确认 graph 最终会把它们映射成外部 `ExtractionResult`，而不是把内部对象直接暴露出去。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_graph.py -q
```
