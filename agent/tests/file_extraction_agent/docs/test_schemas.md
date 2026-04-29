# `test_schemas.py`

## 基本实现思路

这个测试文件同时约束两层 schema：

```text
外部 `service.file_extraction_agent.schemas`
  -> 定义稳定输入输出对象
  -> 包括 TaskSpec / NormalizedBlock / ExtractionResult
内部 `service.file_extraction_agent.impl.schemas`
  -> 定义流程专用对象
  -> 包括 ExtractionInput / FieldEvidence / FieldResolutionDecision / FieldDecision / LookupRecord / FieldReferenceRecord
```

目标是把“外部稳定契约”和“内部流程对象”固定成两层，不再把 broad / resolution / lookup 的实现细节直接塞进全局 schema。

## 测什么

- `TaskSpec` 不允许重复字段名
- `TaskSpec` 支持 `list` 字段类型，resolution 模型可以为这类字段返回 `string[]`
- `ExtractionInput` 能接住 blocks 主输入并提供安全默认值
- `ExtractionInput.blocks` 会把序列化后的 block 字典解析成结构化模型
- `FieldEvidence` 保留 broad 阶段的证据信息
- 外部 `FieldResult` / `FieldTrace` 维持稳定的 `status + result + trace` 结构
- 内部 `RunOptions` / `FieldDecision` / `LookupRecord` 维持流程对象约束
- `RunOptions` 同时约束 lookup 调用预算和 prompt 输入预算
- `FieldResolutionDecision` 是模型返回的轻量字段判断，不携带系统内部 evidence 对象
- `FieldResolutionDecision.value` 的 JSON Schema 分支都带明确 `type`，避免 strict response format 被 provider 拒绝
- lookup 调用次数、lookup 返回条数和 trace action metadata 分开表达
- 整包 `ExtractionResult(status="failed")` 必须说明统一失败原因

## 每个函数在干什么

`test_task_spec_rejects_duplicate_field_names`

- 构造两个同名字段。
- 确认 `TaskSpec` 会拒绝重复 `field_name`。

`test_task_spec_accepts_list_field_and_resolution_value_list`

- 构造 `type=list` 的学术论文名称字段。
- 构造 resolution 模型返回的 `string[]` 值。
- 确认 schema 允许多值字段用数组表达，而不是要求调用方拼接成字符串。

`test_extraction_input_accepts_blocks_with_safe_defaults`

- 构造最小合法的 `ExtractionInput`。
- 确认内部入口对象会保留 blocks、bbox、默认 options 和 metadata。
- 确认默认 `max_lookup_calls_per_field=1`、`lookup_top_k=3`、`max_prompt_blocks=200`、`max_prompt_block_chars=2000`。

`test_extraction_input_parses_serialized_blocks_into_structured_models`

- 用序列化字典构造 block。
- 确认它会被解析成 `NormalizedBlock` / `NormalizedBoundingBox`。

`test_extraction_input_requires_blocks`

- 构造缺少 blocks 的 `ExtractionInput`。
- 确认内部入口对象会拒绝不完整主输入。

`test_field_evidence_keeps_relevant_blocks_and_evidence`

- 构造一份内部 `FieldEvidence`。
- 确认证据文本、block id、证据 refs 和 notes 不会丢失。

`test_field_result_rejects_failed_status_with_value`

- 给外部 `FieldResult(status="failed")` 塞一个 `value`。
- 确认外部纯结果对象会拒绝这种矛盾状态。

`test_field_trace_requires_reason_or_failure_reason_by_status`

- 分别构造缺少 `reason` 的 resolved trace 和缺少 `failure_reason` 的 failed trace。
- 确认外部 trace 对象会要求每个字段给出解释。

`test_extraction_result_separates_result_and_trace`

- 构造新的 `ExtractionResult(status + result + trace)`。
- 确认外部返回对象仍然把业务结果和留痕拆开。
- 确认未显式失败时，顶层状态默认为 `completed`。

`test_failed_extraction_result_requires_failure_reason`

- 构造没有 `failure_reason` 的整包 failed 返回。
- 确认 schema 会拒绝这种不可审计的失败状态。
- 再构造带统一失败原因的 failed 返回，确认其可被正常序列化和传递。

`test_run_options_reject_non_positive_lookup_limits`

- 分别构造非法 `max_lookup_calls_per_field=0`、`lookup_top_k=0` 和 `max_prompt_blocks=0`。
- 确认内部运行选项会拒绝非正数，并且 lookup 与 prompt budget 控制维度互不混用。

`test_field_decision_rejects_failed_status_with_value`

- 给内部 `FieldDecision(status="failed")` 塞一个 `value`。
- 确认内部定案对象也会维持一致的状态约束。

`test_field_resolution_action_uses_lightweight_model_decision`

- 构造 `FieldResolutionAction(action="final_decision")`。
- 其中的 decision 只包含 `status/value/used_block_ids/related_fields/reason`。
- 确认模型决策对象不要求也不暴露 `evidence` 字段。

`test_field_resolution_action_value_schema_is_strict_provider_compatible`

- 读取 `FieldResolutionAction.model_json_schema()`。
- 确认 `FieldResolutionDecision.value` 的每个 `anyOf` 分支都有明确 `type`。
- 防止 `Any | None` 生成 `{}` 分支，导致 provider 在创建 strict `response_format` 时返回 400。

`test_lookup_record_can_be_projected_to_trace_action`

- 构造内部 `LookupRecord`。
- 确认它可以映射成对外 `TraceAction`。
- 确认 `target_field_name`、`returned_block_ids`、`returned_to_model` 会写入 action metadata。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_schemas.py -q
```
