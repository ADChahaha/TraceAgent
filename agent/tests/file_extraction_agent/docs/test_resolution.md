# `test_resolution.py`

## 基本实现思路

`service.file_extraction_agent.impl.resolution.runner` 负责基于候选池做字段最终定案。它只编排模型动作、执行允许的工具，并要求最终 `final_decision` 只能引用 `candidate_id`。

```text
GraphState.candidates + TaskSpec.fields + extractor_client
  -> run_resolution_stage(...) 按字段顺序运行
  -> build_resolution_messages(...) 提供候选池摘要和工具历史
  -> extractor_client.invoke(output_schema=FieldResolutionAction, tools=[候选读取/搜索/写候选])
  -> 模型可请求 get_candidate_bundle / search_grep / add_resolution_candidate
  -> final_decision(status, value, candidate_ids, reason) 是唯一正常出口
  -> build_field_decision_from_final_action(...) 校验 candidate_ids 属于当前字段候选池
  -> 写回 GraphState.field_decisions[field_name]
```

搜索和补候选的触发点必须来自模型动作。系统不再保留独立 `validation` 阶段，也不会用未入候选池的 ref 直接做最终字段证据。

## 测什么

- resolution 按 `task_spec.fields` 逐字段请求 `FieldResolutionAction`。
- resolved final decision 必须引用当前字段已有的 `candidate_id`。
- 模型引用不存在的 candidate id 会被拒绝。
- resolution 可以先用统一 search 搜索，再把命中的 ref 写成 resolution 候选，最后引用该候选定案。
- 模型请求 `get_candidate_bundle` 时会记录候选读取动作。

## 每个函数在干什么

`test_run_resolution_stage_final_decision_must_reference_candidate_ids`

- 为两个字段预先写入 broad 候选。
- fake client 逐字段返回 `final_decision`。
- 确认定案结果写入 `state.field_decisions`，并记录 `final_decision` 动作。

`test_run_resolution_stage_rejects_unknown_candidate_ids`

- fake client 返回不存在的 candidate id。
- 确认 runner 在组装 `FieldDecision` 前拒绝。

`test_run_resolution_stage_can_search_and_add_resolution_candidate_before_decision`

- fake client 先请求 `search_grep`，再请求 `add_resolution_candidate`。
- 最后用新 candidate id 返回 `final_decision`。
- 确认候选来源为 `resolution`，并记录三步动作。

`test_run_resolution_stage_records_candidate_bundle_reads`

- fake client 第一轮请求候选池。
- 确认下一轮 prompt 能看到候选摘要，并且 trace 中保留 `get_candidate_bundle`。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
