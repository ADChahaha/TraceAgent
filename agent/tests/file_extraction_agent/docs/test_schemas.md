# `test_schemas.py`

## 基本实现思路

`file_extraction_agent.schemas` 负责定义字段抽取阶段的公共数据契约。它不是执行图本身，也不直接访问模型，而是先把“blocks 主输入长什么样、broad extraction 要产出什么、resolution 最终结果与 trace 怎么返回”固定下来。

这层可以按下面的 pipeline 理解：

```text
调用方先把 document_processor 结果里的 blocks 摊平，并保留每个 block 上的 document_id
  -> 用 NormalizedBlock / TaskSpec / GraphInput 固定图入口输入
  -> broad extraction 为每个字段产出 evidence bundle，不产最终 candidate
  -> resolution 产出纯业务结果 ResolvedFieldResult
  -> 同时把 broad / cross / lookup / reason 收口进 FieldTraceRecord
  -> processor 最后返回 ExtractionResult(result + trace)
```

这个测试文件的目标就是把这套契约钉住，避免后面实现 graph、tools、resolution 时把输入输出结构改散。

## 测什么

- `TaskSpec` 不允许重复字段名
- `GraphInput` 能接住以 `blocks` 为主输入的最小合法输入，并提供安全默认值
- `GraphInput` 不允许缺少 blocks 主输入
- `GraphInput.blocks` 会把序列化后的块数据解析成结构化模型
- broad extraction 字段输出保留 evidence bundle，不依赖 `candidate_values`
- `ResolvedFieldResult` 的 `resolved/failed` 状态约束
- `FieldTraceRecord` 会按状态要求定案原因或失败原因
- `ExtractionResult` 顶层拆成 `result` 与 `trace`
- `RunConfig` 的关键执行限制

## 每个函数在干什么

`test_task_spec_rejects_duplicate_field_names`

- 构造两个同名字段。
- 确认 `TaskSpec` 会拒绝重复 `field_name`，避免后续 graph 和 resolution 定位字段时发生歧义。

`test_graph_input_accepts_normalized_documents_with_safe_defaults`

- 构造最小 blocks 输入和 `TaskSpec`。
- 检查 `GraphInput` 是否能正常接住。
- 同时确认 `document_id`、结构化 `blocks`、备用 `md_list`、`metadata`、`run_config` 这些默认值和关键标识安全可用。

`test_graph_input_parses_serialized_blocks_into_structured_models`

- 构造一份带序列化 block 字典的 `GraphInput`。
- 确认 schema 会把它解析成明确的 `NormalizedBlock` / `NormalizedBoundingBox`，而不是保留成裸字典。

`test_graph_input_requires_blocks`

- 构造一个缺少 blocks 的 `GraphInput`。
- 确认 schema 会拒绝这种不完整的主输入。

`test_field_evidence_bundle_keeps_relevant_blocks_and_evidence`

- 构造一个 broad evidence bundle。
- 确认字段名、相关 block id、证据文本、证据位置和局部说明不会丢失。
- 这个测试固定 broad 阶段“选材料，不定案”的契约。

`test_resolved_field_result_rejects_failed_status_with_final_value`

- 故意给 `failed` 状态塞一个 `final_value`。
- 确认纯结果对象会拦住这种互相矛盾的结果。

`test_field_trace_record_requires_reason_or_failure_reason_by_status`

- 分别构造缺少 `reason` 的 `resolved` trace 和缺少 `failure_reason` 的 `failed` trace。
- 确认 trace 层会要求每个字段给出定案或失败解释。

`test_extraction_result_separates_result_and_trace`

- 构造新的 `ExtractionResult(result + trace)`。
- 确认纯结果与字段级 trace 会分开序列化。

`test_run_config_rejects_non_positive_lookup_limit`

- 构造非法的 `max_extra_lookups_per_field=0`。
- 确认运行配置会拒绝非正数，避免 extra lookup 控制失效。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_schemas.py -q
```
