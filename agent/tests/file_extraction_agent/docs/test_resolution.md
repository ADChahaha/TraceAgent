# `test_resolution.py`

## 基本实现思路

`file_extraction_agent.impl.resolution` 负责把 broad 阶段的 `FieldEvidence` 收口成内部 `FieldDecision`。

```text
EvidenceCollection + TaskSpec
  -> 按 task_spec.fields 固定输出顺序
  -> 找到每个字段对应的 evidence
  -> 有 extractor_client 时逐字段调用模型做 FieldDecision
  -> 如果字段定义了 validation_rules，就按通用规则校验或覆盖模型结果
  -> 有 evidence_texts 时产出 resolved decision
  -> 缺失 evidence 时按 lookup_hints 从全量 blocks 补查
  -> 补查仍无结果时产出 failed decision
  -> 把 field_decisions 写回 GraphState
```

当前保留 deterministic 兜底：没有传入模型客户端时，优先用 evidence 或补查命中的文本做最小定案。
如果字段配置了 `validation_rules`，resolution 会按通用规则对模型结果做校验或覆盖；这些规则只描述列名、筛选条件、排除条件和跨字段计数，不把具体业务词写进代码。

## 测什么

- resolution 会按 `task_spec.fields` 顺序输出字段决策
- 缺失字段时会补一个显式失败决策
- evidence 与最终 value 分离保存
- `run_resolution(...)` 会把字段决策写回 `GraphState`
- `run_resolution(...)` 在收到模型客户端时，会逐字段调用结构化输出拿回 `FieldDecision`
- `validation_rules.table_rows` 能按通用表格列规则筛选证据，并覆盖模型混入的无关行
- `validation_rules.operation=count_items` 能根据前置字段条目数做一致性收口
- broad 阶段缺少证据时，resolution 会按 lookup hints 执行一次全局补查并记录 `LookupRecord`
- 对文明寝室这类表格证据，会把楼栋、文明寝室房间号和数量从 evidence 行里归一化出来

## 每个函数在干什么

`test_resolve_fields_uses_task_spec_order_and_fills_missing_outputs`

- 构造只命中一个字段的 evidence。
- 确认 resolution 会保序输出，并给缺失字段补失败决策。

`test_resolve_fields_keeps_evidence_separate_from_result_value`

- 构造带 notes 的 evidence。
- 确认最终 `value` 和原始 evidence 明细不会混在一起。

`test_run_resolution_reads_evidence_collection_and_writes_decisions_to_state`

- 先往 `GraphState` 写好 `evidence_collection`。
- 调用 `run_resolution(...)`。
- 确认状态里会被写回最终 `field_decisions`。

`test_run_resolution_invokes_model_client_for_field_decisions`

- 构造一个可记录调用的 fake extractor client。
- 调用 `run_resolution(...)` 并传入 fake client。
- 确认 resolution 按 task spec 字段顺序逐字段请求 `FieldDecision` 结构化输出。

`test_run_resolution_records_lookup_when_evidence_is_missing`

- 构造 broad 阶段缺失 `amount` 证据，但全量 blocks 中有“应付金额”的输入。
- 启用 extra lookup 后调用 `run_resolution(...)`。
- 确认字段通过补查定案，并在 `lookup_records` 中保留目标字段、返回 block id 和使用标记。

`test_run_resolution_applies_generic_table_row_rules_after_model_decision`

- 构造一个通用表格，包含 `selected` 和 `rejected` 两类状态行。
- fake 模型故意把 rejected 行混入最终结果。
- 在字段的 `validation_rules` 中声明 `source_type=table_rows`、`target_column=room`、`filter status == selected`、`exclude status == rejected`。
- 确认 resolution 不硬编码任何业务词，而是按规则把结果纠正成 `A101, A103`，并让 count 字段按源字段条目数得到 `2`。

`test_resolve_fields_normalizes_civilized_dormitory_table_evidence`

- 构造一组 markdown 表格行，其中多行标注为“文明寝室”。
- 确认 `building_name` 会定案成楼栋名，而不是整行文本。
- 确认 `civilized_dormitory_rooms` 会按出现顺序定案成房间号列表字符串。
- 确认 `civilized_dormitory_count` 会定案成文明寝室条目数。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_resolution.py -q
```
