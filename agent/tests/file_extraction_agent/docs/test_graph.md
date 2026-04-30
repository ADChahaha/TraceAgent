# `test_graph.py`

## 基本实现思路

`service.file_extraction_agent.impl.graph` 负责编排 broad 和 resolution 两个阶段，并把候选池里的内部引用映射成对外 `ExtractionResult`。

```text
ExtractionInput + ExtractorClient
  -> build_graph_state(extraction_input)
  -> run_broad_stage(state, extractor_client)
  -> run_resolution_stage(state, extractor_client)
  -> map_state_to_result(state)
  -> candidate_id -> ref -> paragraph/table index 回查证据定位
  -> 输出 ExtractionResult(status + result + trace)
```

如果 broad 或 resolution 中途抛出模型 API、结构化输出或流程校验异常，graph 不把异常继续向外抛，而是统一返回 `status="failed"` 的 `ExtractionResult`。返回结果会保留失败前已经写入的候选、字段定案和 warnings，并为未完成字段补充 failed trace。
如果 broad 阶段在某个字段失败，已经 `finish_broad` 的字段只保留自己的 broad 动作，不额外挂 `model_call_error`；错误 action 只挂到第一个未完成 broad 的字段上。

## 测什么

- graph 会先跑 broad，再跑 resolution。
- graph 会把同一个 `extractor_client` 继续传给两个阶段。
- graph 会用 `candidate_id -> ref -> index` 生成外部 evidence。
- broad 失败时，graph 会返回整包 failed，而不是抛裸异常。
- broad 失败收口时，不把失败字段的 `model_call_error` 追加到已经 `finish_broad` 的字段 trace 上。
- resolution 中途失败时，graph 会保留失败前已经完成的字段 trace，并为剩余字段补 failed。

## 每个函数在干什么

`test_run_extraction_graph_runs_broad_stage_then_resolution_stage`

- 用 monkeypatch 替换 broad 和 resolution。
- 记录调用顺序，并让 broad 先写入候选。
- 确认 resolution 紧跟其后运行，而且拿到的是同一个状态和同一个模型客户端。

`test_map_state_to_result_resolves_candidate_refs_to_external_trace`

- 构造候选和字段定案。
- 确认 graph 最终会把候选 ref 回查成外部 `EvidenceSummary`，并保留工具动作。

`test_run_extraction_graph_returns_failed_result_when_broad_fails`

- 用 monkeypatch 让 broad 节点模拟 API timeout。
- 确认 graph 返回 `status="failed"`，所有 schema 字段都变成 failed。
- 确认失败原因、失败阶段和 `model_call_error` action 会写进 trace。

`test_broad_failure_action_is_attached_to_first_unfinished_broad_field`

- 用 monkeypatch 模拟第一个字段已经写入 `finish_broad`，第二个字段 broad 失败。
- 确认第一个字段 trace 只保留 `finish_broad`。
- 确认 `model_call_error` 只写到第一个未完成 broad 的字段，并且 metadata 区分 completed/pending 字段。

`test_run_extraction_graph_preserves_completed_decisions_before_resolution_failure`

- 先让 broad 写入候选。
- 再让 resolution 在第一个字段完成定案后模拟 API quota 失败。
- 确认第一个字段的 resolved 结果保留，第二个字段变成 failed。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_graph.py -q
```
