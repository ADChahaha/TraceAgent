# `test_broad_extraction.py`

## 基本实现思路

这个测试文件约束 `service.file_extraction_agent.impl.broad.runner` 的共享 broad loop。

```text
GraphState
  -> run_broad_stage(...) 构造包含所有字段和 pending_fields 的 broad prompt
  -> extractor_client.invoke(output_schema=BroadAction, tools=[search/add/copy])
  -> search_grep 同时检索正文段落和表格行，返回 ref/text
  -> add_broad_candidate 将 ref 写入字段候选池
  -> add_broad_candidate 收到未知 ref 时记录 tool_error，并把错误返回给下一轮模型修正
  -> copy_field_candidates 可在 broad 阶段把一个字段候选复制到另一个字段
  -> finish_broad 是每个字段 broad 的唯一正常出口
  -> state.candidates / state.broad_finishes / state.actions 保留可追踪状态
```

## 覆盖点

- broad 节点会请求 `BroadAction`，并直接注入当前阶段允许的工具名。
- broad loop 可以按 `search -> add_candidate -> finish_broad` 完成字段候选召回。
- broad loop 可以调用 `copy_field_candidates` 复制字段候选，且工具结果不把来源候选正文塞回下一轮 prompt。
- broad loop 遇到模型传入未知 ref 时不会整单失败，而是返回 `tool_error` observation 让模型改用合法 ref。
- broad 不暴露 `count_field_candidates`；派生数量字段在 resolution 阶段处理。
- `status=enough_evidence` 时必须已有候选。
- 模型动作的 `field_name` 必须属于 `task_spec.fields`。
- 返回值仍然是同一个 `GraphState`。

## 每个函数在干什么

`test_run_broad_stage_uses_search_add_candidate_and_finish_actions`

- 构造一份最小 `ExtractionInput` 和空状态。
- fake client 依次返回搜索、写候选、结束 broad 的动作。
- 确认候选池、finish 记录和动作 trace 都写回 state。

`test_run_broad_stage_can_copy_candidates_between_fields_without_returning_text`

- fake client 先给来源字段召回候选并结束来源字段 broad。
- 随后调用 `copy_field_candidates(field_name=目标字段, source_field_name=来源字段)`。
- 确认目标字段得到复制候选，候选来源阶段为 broad，下一轮 prompt 只看到复制数量和 candidate id 摘要。

`test_run_broad_stage_returns_tool_error_for_unknown_ref_and_continues`

- fake client 先搜索，再故意用不存在的 ref 调用 `add_broad_candidate`。
- 确认 runner 把未知 ref 记录成 `tool_error`，下一轮 prompt 能看到错误信息。
- fake client 改用合法 ref 后，broad 可以继续写候选并正常 `finish_broad`。

`test_run_broad_stage_rejects_enough_evidence_without_candidates`

- fake client 直接返回 `finish_broad(enough_evidence)`。
- 确认目标字段没有候选时会被拒绝。

`test_run_broad_stage_rejects_unknown_field_action`

- fake client 返回不存在于 `task_spec.fields` 的字段动作。
- 确认 runner 拒绝未知字段动作，避免候选写错字段。

## 运行方式

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
