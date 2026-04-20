# `test_schemas.py`

## 基本实现思路

`file_extraction_agent.schemas` 负责定义字段抽取阶段的公共数据契约。它不是执行图本身，也不直接访问模型，而是先把“后端聚合后的 session 级输入长什么样、broad extraction 要产出什么、field resolution 要产出什么、最终结果怎么聚合”固定下来。

这层可以按下面的 pipeline 来理解：

```text
backend 先把 document_processor 结果按 session 聚合，并补上 session_id / document_id
  -> 用 NormalizedDocument / TaskSpec / GraphInput 固定图入口输入
  -> broad extraction 为每个字段产出候选值、证据文本、证据位置和局部状态
  -> field resolution 再按字段输出 resolved 或 failed
  -> processor 最后把 broad_output、resolved_fields、run_trace 汇总成 ExtractionResult
```

这个测试文件的目标就是把这套契约钉住，避免后面实现 graph、validation、resolution 时把输入输出结构改散了。

## 测什么

- `TaskSpec` 不允许重复字段名
- `GraphInput` 能接住带 `session_id` 的最小合法输入，并提供安全默认值
- `GraphInput` 不允许缺少后端聚合得到的 `session_id`
- `NormalizedDocument.blocks` 会把序列化后的块数据解析成结构化模型
- broad extraction 字段输出能保留候选值和证据 bundle
- `ResolvedFieldOutput` 的 `resolved/failed` 状态约束
- `ExtractionResult` 的聚合结构
- `RunConfig` 的关键执行限制

## 每个函数在干什么

`test_task_spec_rejects_duplicate_field_names`

- 构造两个同名字段。
- 确认 `TaskSpec` 会拒绝重复 `field_name`，避免后续 graph 和 resolution 定位字段时发生歧义。

`test_graph_input_accepts_normalized_documents_with_safe_defaults`

- 构造带 `session_id` 的最小 `NormalizedDocument` 和 `TaskSpec`。
- 检查 `GraphInput` 是否能正常接住。
- 同时确认 `document_id`、结构化 `blocks`、`metadata`、`run_config` 这些默认值和关键标识安全可用。

`test_normalized_document_parses_serialized_blocks_into_structured_models`

- 构造一份带序列化 block 字典的 `NormalizedDocument`。
- 确认 schema 会把它解析成明确的 `NormalizedBlock` / `NormalizedBoundingBox`，而不是保留成裸字典。

`test_graph_input_requires_backend_session_id`

- 构造一个缺少 `session_id` 的 `GraphInput`。
- 确认 schema 会拒绝这种“还没经过 backend session 聚合”的输入。

`test_broad_extraction_output_keeps_candidate_evidence_bundle`

- 构造一个 broad extraction 字段输出。
- 检查候选值、证据文本、证据位置、局部说明会不会在模型里丢失。

`test_resolved_field_output_rejects_failed_status_with_final_value`

- 故意给 `failed` 状态塞一个 `final_value`。
- 确认 schema 会拦住这种互相矛盾的结果。

`test_resolved_field_output_requires_failure_reason_for_failed_status`

- 构造一个没有 `failure_reason` 的 `failed` 输出。
- 确认失败结果必须说明为什么失败，便于后续治理层审计。

`test_extraction_result_aggregates_broad_output_and_resolved_fields`

- 构造完整的 `ExtractionResult`。
- 检查 broad output、resolved fields、run trace 能否一起稳定序列化。

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
