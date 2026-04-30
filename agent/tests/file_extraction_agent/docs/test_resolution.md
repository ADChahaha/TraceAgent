# `test_resolution.py`

## 基本实现思路

`service.file_extraction_agent.impl.resolution.runner` 负责基于候选池做字段最终定案。它只编排模型动作、执行允许的工具，并要求最终 `final_decision` 只能引用 `candidate_id`。

```text
GraphState.candidates + TaskSpec.fields + extractor_client
  -> run_resolution_stage(...) 构造包含所有字段、pending_fields 和候选池的共享 prompt
  -> build_resolution_messages(...) 提供全字段候选池摘要、已完成字段和工具历史
  -> extractor_client.invoke(output_schema=FieldResolutionAction, tools=[候选读取/搜索/写候选/计数])
  -> 模型可请求 get_candidate_bundle / search_grep / add_resolution_candidate / count_field_candidates
  -> add_resolution_candidate 收到未知 ref 时记录 tool_error，并把错误返回给下一轮模型修正
  -> final_decision(status, value, candidate_ids, reason) 是唯一正常出口
  -> build_field_decision_from_final_action(...) 校验 candidate_ids 属于目标字段候选池
  -> 写回 GraphState.field_decisions[field_name]
```

搜索和补候选的触发点必须来自模型动作。系统不再保留独立 `validation` 阶段，也不会用未入候选池的 ref 直接做最终字段证据。

## 测什么

- resolution 在共享 loop 中请求 `FieldResolutionAction`，每轮动作可指向任意待处理字段。
- resolved final decision 必须引用目标字段已有的 `candidate_id`。
- 模型引用不存在的 candidate id 会被拒绝。
- resolution 可以先用统一 search 搜索，再把命中的 ref 写成 resolution 候选，最后引用该候选定案。
- resolution 遇到模型传入未知 ref 时不会整单失败，而是返回 `tool_error` observation 让模型改用合法 ref。
- 模型请求 `get_candidate_bundle` 时会记录候选读取动作。
- 模型请求 `count_field_candidates` 时会得到指定字段当前候选数量，并记录计数动作。
- 模型必须把 `count_field_candidates` 返回的数字用 `add_resolution_candidate(values=[...])` 写入目标字段候选池，再用 `final_decision` 引用 candidate_id。

## 每个函数在干什么

`test_run_resolution_stage_final_decision_must_reference_candidate_ids`

- 为两个字段预先写入 broad 候选。
- fake client 在共享 loop 中先返回一个字段的 `final_decision`，再统计另一个字段候选数量并完成定案。
- 确认定案结果写入 `state.field_decisions`，并记录 `final_decision` 动作。

`test_run_resolution_stage_rejects_unknown_candidate_ids`

- fake client 返回不存在的 candidate id。
- 确认 runner 在组装 `FieldDecision` 前拒绝。

`test_run_resolution_stage_can_search_and_add_resolution_candidate_before_decision`

- fake client 先请求 `search_grep`，再请求 `add_resolution_candidate`。
- 最后用新 candidate id 返回 `final_decision`。
- 确认候选来源为 `resolution`，并记录三步动作。

`test_run_resolution_stage_returns_tool_error_for_unknown_ref_and_continues`

- fake client 先搜索，再故意用不存在的 ref 调用 `add_resolution_candidate`。
- 确认 runner 把未知 ref 记录成 `tool_error`，下一轮 prompt 能看到错误信息。
- fake client 改用合法 ref 后，resolution 可以继续写候选并用该 candidate 完成定案。

`test_run_resolution_stage_records_candidate_bundle_reads`

- fake client 第一轮请求候选池。
- 确认下一轮 prompt 能看到候选摘要，并且 trace 中保留 `get_candidate_bundle`。

`test_run_resolution_stage_requires_model_final_decision_after_count_tool`

- 先完成来源字段定案。
- fake client 对来源字段调用 `count_field_candidates(field_name=来源字段)`。
- 确认 runner 只记录计数并把数字放入下一轮 prompt，随后 fake client 用 `add_resolution_candidate(values=[...])` 写入目标字段候选并显式返回 `final_decision`。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
