# `test_graph.py`

## 基本实现思路

`file_extraction_agent.impl.graph` 负责串联内部节点，并把内部 `FieldDecision` 映射成对外 `ExtractionResult`。

```text
ExtractionInput + ExtractorClient
  -> build_graph_state(extraction_input)
  -> run_broad_extraction(state, extractor_client)
  -> run_resolution(state, extractor_client)
  -> 读取 state.field_decisions / state.warnings
  -> 映射成 ExtractionResult(status + result + trace)
```

如果 broad 或 resolution 中途抛出模型 API、结构化输出或流程校验异常，graph 不把异常继续向外抛，而是统一返回 `status="failed"` 的 `ExtractionResult`。返回结果会保留失败前已经写入的 `evidence_collection`、`field_decisions` 和 `warnings`，并为未完成字段补充 failed trace。

## 测什么

- graph 会先跑 broad，再跑 resolution
- resolution 读取的是 broad 写回后的同一个状态对象
- graph 会把同一个 `extractor_client` 继续传给 resolution 阶段
- graph 最后会把内部 `FieldDecision` 映射成外部 `FieldResult` / `FieldTrace`
- broad 失败时，graph 会返回整包 failed，而不是抛裸异常
- resolution 中途失败时，graph 会保留失败前已经完成的字段 trace，并为剩余字段补 failed

## 每个函数在干什么

`test_run_extraction_graph_runs_broad_extraction_then_resolution`

- 用 monkeypatch 替换 broad 和 resolution。
- 记录调用顺序，并让 broad 先写入 `evidence_collection`。
- 确认 resolution 紧跟其后运行，而且拿到的是同一个状态和同一个模型客户端。

`test_run_extraction_graph_maps_internal_decisions_to_external_result`

- 构造内部 evidence 和 decision。
- 确认 graph 最终会把它们映射成外部 `ExtractionResult`，而不是把内部对象直接暴露出去。

`test_run_extraction_graph_returns_failed_result_when_broad_fails`

- 用 monkeypatch 让 broad 节点模拟 API timeout。
- 确认 graph 返回 `status="failed"`，所有 schema 字段都变成 failed。
- 确认失败原因、失败阶段和 `model_call_error` action 会写进 trace。

`test_run_extraction_graph_preserves_trace_before_resolution_failure`

- 先让 broad 写入两字段 evidence。
- 再让 resolution 在第一个字段完成定案后模拟 API quota 失败。
- 确认第一个字段的 resolved 结果保留，第二个字段变成 failed，并沿用 broad evidence 作为失败前可追踪信息。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_graph.py -q
```
