# `test_broad_extraction.py`

## 基本实现思路

这个测试文件约束 `service.file_extraction_agent.impl.broad.runner` 的字段级 broad loop。

```text
GraphState
  -> run_broad_stage(...) 按 task_spec.fields 顺序遍历字段
  -> run_broad_loop_for_field(...) 构造 broad prompt
  -> extractor_client.invoke(output_schema=BroadAction, tools=[search/add])
  -> search_grep 同时检索正文段落和表格行，返回 ref/text
  -> add_broad_candidate 将 ref 写入字段候选池
  -> finish_broad 是当前字段 broad 的唯一正常出口
  -> state.candidates / state.broad_finishes / state.actions 保留可追踪状态
```

## 覆盖点

- broad 节点会请求 `BroadAction`，并直接注入当前阶段允许的工具名。
- broad loop 可以按 `search -> add_candidate -> finish_broad` 完成字段候选召回。
- `status=enough_evidence` 时必须已有候选。
- 模型动作的 `field_name` 必须等于当前字段。
- 返回值仍然是同一个 `GraphState`。

## 每个函数在干什么

`test_run_broad_stage_uses_search_add_candidate_and_finish_actions`

- 构造一份最小 `ExtractionInput` 和空状态。
- fake client 依次返回搜索、写候选、结束 broad 的动作。
- 确认候选池、finish 记录和动作 trace 都写回 state。

`test_run_broad_stage_rejects_enough_evidence_without_candidates`

- fake client 直接返回 `finish_broad(enough_evidence)`。
- 确认当前字段没有候选时会被拒绝。

`test_run_broad_stage_rejects_action_for_another_field`

- 当前循环正在处理 `invoice_no`。
- fake client 返回 `amount` 字段动作。
- 确认 runner 拒绝跨字段动作，避免候选写错字段。

## 运行方式

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
