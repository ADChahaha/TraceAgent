# `test_schemas.py`

## 基本实现思路

这个测试文件同时约束外部稳定契约和内部阶段对象。

```text
外部 schemas.py
  -> TaskSpec / NormalizedBlock / RunOptions / ExtractionResult
内部 impl/schemas.py
  -> ExtractionInput / SearchResult / Candidate / ToolActionRecord
  -> BroadAction / FieldResolutionAction / FieldDecision
```

外部对象面向调用方保持稳定，内部对象只服务 broad loop、resolution loop、候选池和 trace 映射。

## 测什么

- `TaskSpec` 不允许重复字段名。
- `RunOptions` 默认提供 prompt 和候选预算。
- `SearchResult.ref` 和 `Candidate.candidate_id` 是两个不同层级的引用。
- broad 和 resolution 的 action schema 会校验 terminal action 的必要字段。
- resolved `FieldDecision` 必须引用候选证据。
- 外部 `FieldResult` / `FieldTrace` / `ExtractionResult` 继续保持 `result + trace` 结构。

## 每个函数在干什么

`test_task_spec_rejects_duplicate_field_names`

- 构造两个同名字段。
- 确认 `TaskSpec` 会拒绝重复 `field_name`。

`test_task_spec_accepts_list_field_and_resolution_value_list`

- 构造 `type=list` 字段。
- 确认 resolution terminal action 可以返回字符串数组值。

`test_extraction_input_accepts_blocks_with_safe_defaults`

- 构造最小合法的 `ExtractionInput`。
- 确认内部入口对象会保留 blocks、bbox、默认 options 和 metadata。

`test_internal_tool_and_candidate_schemas_keep_refs_separate_from_candidates`

- 构造 `SearchResult`、`Candidate` 和 `ToolActionRecord`。
- 确认 grep ref、候选 id 和动作记录各自独立。

`test_broad_action_validates_terminal_finish_shape`

- 构造合法 `finish_broad`。
- 再构造缺少 status/reason 的 `finish_broad`，确认 schema 拒绝。

`test_field_decision_requires_candidate_ids_for_resolved_status`

- 构造缺少 candidate id 的 resolved 决策。
- 确认内部定案对象拒绝不可追踪的 resolved 结果。

`test_extraction_input_parses_serialized_blocks_into_structured_models`

- 用序列化字典构造 block。
- 确认它会被解析成 `NormalizedBlock` / `NormalizedBoundingBox`。

`test_extraction_input_requires_blocks`

- 构造缺少 blocks 的 `ExtractionInput`。
- 确认内部入口对象会拒绝不完整主输入。

`test_field_result_rejects_failed_status_with_value`

- 给外部 `FieldResult(status="failed")` 塞一个 `value`。
- 确认外部纯结果对象会拒绝这种矛盾状态。

`test_field_trace_requires_reason_or_failure_reason_by_status`

- 分别构造缺少 `reason` 的 resolved trace 和缺少 `failure_reason` 的 failed trace。
- 确认外部 trace 对象会要求每个字段给出解释。

`test_extraction_result_separates_result_and_trace`

- 构造 `ExtractionResult(result + trace)`。
- 确认业务结果和留痕仍然分开序列化。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_schemas.py -q
```
