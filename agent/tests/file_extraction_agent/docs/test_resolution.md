# `test_resolution.py`

## 基本实现思路

`file_extraction_agent.impl.resolution` 负责把 broad 阶段的 `FieldEvidence` 交给模型做字段级最终定案。代码只负责编排模型动作、执行模型请求的工具，并在模型输出后调用 `impl.validation` 做确定性后处理；不能在没有模型输出的情况下把 evidence 文本自行改成最终字段值。

```text
GraphState.evidence_collection + TaskSpec.fields + extractor_client
  -> 校验 broad 阶段已经写入 EvidenceCollection
  -> 校验必须传入 extractor_client，禁止本地 evidence 兜底
  -> 按 task_spec.fields 逐字段请求 FieldResolutionAction
  -> 如果模型返回 final_decision，取其中轻量 FieldResolutionDecision
  -> 系统用 decision.used_block_ids 回查 NormalizedBlock
  -> 系统组装内部 FieldEvidence / FieldDecision
  -> 如果模型返回 lookup_blocks，按模型给出的 reason / hints 执行 lookup_blocks_for_field(...)
  -> 如果模型返回 get_field_bundle，读取对应字段 broad bundle 并记录 field_reference action
  -> 把 trace-action 形状的 tool_records / tool_evidence 追加进下一轮该字段模型请求
  -> 最终仍由模型返回轻量字段判断
  -> 调用 validation.apply_validation_rules(...) 应用通用 validation_rules
  -> 调用 validation.apply_field_constraints(...) 按 FieldDefinition 做 required / enum_values / type 基础约束校验
  -> 写回 GraphState.field_decisions
```

lookup 的触发点必须来自模型动作：即使 broad 阶段缺证据、全量 blocks 中存在可匹配内容，系统也不能自己调用 lookup 并自行定案。

## 测什么

- resolution 必须先拿到 broad 阶段的 `EvidenceCollection`。
- resolution 必须传入模型客户端，不能走本地 fallback。
- resolution 按 `task_spec.fields` 逐字段请求 `FieldResolutionAction`。
- 模型 final decision 只需要给 `used_block_ids`，系统负责绑定 evidence / refs。
- 模型返回不存在的 `used_block_ids` 时会被拒绝。
- 模型返回结构合法但不满足字段定义的值时，系统会把字段降级为 failed 并记录 `field_constraint` action。
- lookup 只在模型返回 `lookup_blocks` 动作时执行，并把 `global_lookup` action 并入最终 trace。
- validation 覆盖最终 evidence 后，lookup 的 `used_in_final_decision` 会按覆盖后的 evidence 重新计算。
- `max_lookup_calls_per_field` 限制 lookup 调用次数，`lookup_top_k` 限制每次返回的 blocks 数量。
- 模型请求 `get_field_bundle` 时会记录 `field_reference` action。
- 模型没有请求 lookup 时，缺证据字段保持模型给出的失败结果。
- `validation_rules.table_rows` 和 `operation=count_items` 会作为通用规则校正模型结果，并记录 `validation_rule` action。

## 每个函数在干什么

`test_run_resolution_requires_evidence_collection_before_model_resolution`

- 构造未写入 `evidence_collection` 的状态。
- 确认 resolution 会在调用模型前报错，避免跳过 broad 阶段。

`test_run_resolution_requires_model_client_and_does_not_use_local_fallback`

- 构造已有 broad evidence 的状态，但不传模型客户端。
- 确认 resolution 直接报错，并且不会写入本地兜底生成的 `field_decisions`。

`test_run_resolution_invokes_model_action_for_each_field_decision`

- 构造一个 fake extractor client 返回 `final_decision` 动作。
- 确认 resolution 对每个 task field 都请求 `FieldResolutionAction`，并把模型决策写回状态。
- 确认模型只返回 `used_block_ids` 时，系统能从输入 blocks 绑定 evidence 文本。

`test_run_resolution_rejects_unknown_used_block_ids_from_model_decision`

- fake 模型返回一个不存在的 `used_block_ids`。
- 确认 resolution 在组装内部 `FieldDecision` 前拒绝该结果，避免 trace 指向不可追踪来源。

`test_run_resolution_downgrades_invalid_enum_value_to_failed_decision`

- fake 模型对 enum 字段返回一个不在 `enum_values` 内的 resolved 值。
- 确认系统不把该结果当成已解决字段，而是降级为 failed。
- 确认 trace 中记录 `field_constraint` action，说明失败来自字段约束校验。

`test_run_resolution_only_uses_lookup_when_model_requests_it`

- fake 模型第一轮返回 `lookup_blocks` 动作。
- 确认系统按模型请求执行 lookup，并在第二轮把 trace-action 形状的 `tool_records` 交回模型。
- 确认 `lookup_top_k=2` 会返回两条 block id。
- 确认最终 `FieldDecision` 中保留 lookup 记录，且只标记 `returned_to_model=True`，不在 lookup 调用时直接假定 `used_in_final_decision=True`。

`test_run_resolution_recomputes_lookup_usage_after_validation_override`

- fake 模型先请求 lookup，并在 final decision 中引用 lookup 返回的 block。
- validation_rules 随后用表格规则把最终 evidence 覆盖到另一个 block。
- 确认最终 lookup record 仍保留 returned 记录，但 `used_in_final_decision=False`。

`test_run_resolution_enforces_lookup_call_limit`

- fake 模型连续请求 `lookup_blocks`。
- 设置 `max_lookup_calls_per_field=1`。
- 确认第二次 lookup 请求会被拒绝，避免模型无限补查。

`test_run_resolution_records_field_reference_action_when_model_requests_bundle`

- fake 模型在确定金额字段前请求读取发票号字段 bundle。
- 确认下一轮 prompt 中出现 `field_reference` action。
- 确认最终 trace 保留该 action，且 `related_fields` 仍来自模型最终声明。

`test_run_resolution_records_missing_field_reference_as_returned_tool_record`

- fake 模型请求一个不存在的字段 bundle。
- 确认下一轮 prompt 中仍然出现 `field_reference` action，且 `found=False`。
- 确认“未命中”这个工具结果也被标记为 `returned_to_model=True`，避免负结果从 trace 中消失。

`test_run_resolution_does_not_lookup_missing_evidence_without_model_request`

- broad 阶段缺少金额 evidence，但全量 blocks 中存在可匹配金额文本。
- fake 模型直接返回失败定案，不请求工具。
- 确认系统不会因为本地规则自动 lookup。

`test_run_resolution_applies_generic_table_row_rules_after_model_decision`

- 构造一个通用表格，包含 `selected` 和 `rejected` 两类状态行。
- fake 模型故意把 rejected 行混入最终结果。
- 在字段的 `validation_rules` 中声明 `source_type=table_rows`、`target_column=room`、`filter status == selected`、`exclude status == rejected`。
- 确认 resolution 不硬编码业务词，而是按规则纠正列表字段，并让 count 字段按源字段条目数得到 `2`。
- 确认列表字段和计数字段都会记录 `validation_rule` action，说明规则访问过哪些证据。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
