# `test_resolution.py`

## 基本实现思路

`file_extraction_agent.impl.resolution` 负责把 broad 阶段的 `FieldEvidence` 交给模型做字段级最终定案。代码只负责编排模型动作、执行模型请求的工具、应用通用 `validation_rules`，不能在没有模型输出的情况下把 evidence 文本自行改成最终字段值。

```text
GraphState.evidence_collection + TaskSpec.fields + extractor_client
  -> 校验 broad 阶段已经写入 EvidenceCollection
  -> 校验必须传入 extractor_client，禁止本地 evidence 兜底
  -> 按 task_spec.fields 逐字段请求 FieldResolutionAction
  -> 如果模型返回 final_decision，取其中 FieldDecision
  -> 如果模型返回 lookup_blocks，按模型给出的 reason / hints 执行 lookup_blocks_for_field(...)
  -> 把 tool_records / tool_evidence 追加进下一轮该字段模型请求
  -> 最终仍由模型返回 FieldDecision
  -> 应用通用 validation_rules 后写回 GraphState.field_decisions
```

lookup 的触发点必须来自模型动作：即使 broad 阶段缺证据、全量 blocks 中存在可匹配内容，系统也不能自己调用 lookup 并自行定案。

## 测什么

- resolution 必须先拿到 broad 阶段的 `EvidenceCollection`。
- resolution 必须传入模型客户端，不能走本地 fallback。
- resolution 按 `task_spec.fields` 逐字段请求 `FieldResolutionAction`。
- lookup 只在模型返回 `lookup_blocks` 动作时执行，并把记录并入最终 trace。
- 模型没有请求 lookup 时，缺证据字段保持模型给出的失败结果。
- `validation_rules.table_rows` 和 `operation=count_items` 仍作为通用规则校正模型结果。

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

`test_run_resolution_only_uses_lookup_when_model_requests_it`

- fake 模型第一轮返回 `lookup_blocks` 动作。
- 确认系统按模型请求执行 lookup，并在第二轮把 `tool_records` 交回模型。
- 确认最终 `FieldDecision` 中保留 lookup 记录且标记为用于最终定案。

`test_run_resolution_does_not_lookup_missing_evidence_without_model_request`

- broad 阶段缺少金额 evidence，但全量 blocks 中存在可匹配金额文本。
- fake 模型直接返回失败定案，不请求工具。
- 确认系统不会因为本地规则自动 lookup。

`test_run_resolution_applies_generic_table_row_rules_after_model_decision`

- 构造一个通用表格，包含 `selected` 和 `rejected` 两类状态行。
- fake 模型故意把 rejected 行混入最终结果。
- 在字段的 `validation_rules` 中声明 `source_type=table_rows`、`target_column=room`、`filter status == selected`、`exclude status == rejected`。
- 确认 resolution 不硬编码业务词，而是按规则纠正列表字段，并让 count 字段按源字段条目数得到 `2`。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
