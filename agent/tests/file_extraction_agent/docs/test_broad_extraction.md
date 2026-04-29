# `test_broad_extraction.py`

## 基本实现思路

这个测试文件约束 `service.file_extraction_agent.impl.broad_extraction` 的第一阶段节点行为。

```text
GraphState(extraction_input=..., evidence_collection=None)
  -> run_broad_extraction(...) 读取 state.extraction_input
  -> build_broad_extraction_messages(extraction_input)
  -> extractor_client.invoke(output_schema=EvidenceCollection, messages=...)
  -> 如果模型对同一个 field_name 返回多条 evidence，先按原文顺序合并成一个 bundle
  -> 校验 EvidenceCollection 覆盖 task_spec 中的所有字段
  -> 校验 broad 没有返回 schema 外字段
  -> 校验 relevant_block_ids / evidence_refs.block_id 都来自输入 blocks
  -> 将返回的 EvidenceCollection 写入 state.evidence_collection
```

## 覆盖点

- 节点会请求 `EvidenceCollection`
- 节点会拒绝缺失字段和 schema 外字段
- 节点会把同名字段的多条 evidence 合并成一个 bundle，再进入 resolution
- 节点会拒绝 broad 引用不存在的 block id，或返回缺少 `block_id` 的 evidence ref
- 节点会把输出写回 `state.evidence_collection`
- 返回值仍然是同一个 `GraphState`

## 每个函数在干什么

`test_run_broad_extraction_invokes_client_and_writes_output_to_state`

- 构造一份最小 `ExtractionInput` 和空状态。
- 用假的 extractor client 返回固定 `EvidenceCollection`。
- 确认 broad 节点会按新内部契约写回状态。

`test_run_broad_extraction_rejects_missing_task_field`

- 构造包含两个 task 字段的输入。
- fake 模型只返回其中一个字段的 evidence。
- 确认 broad 校验会在进入 resolution 前拒绝缺失字段。

`test_run_broad_extraction_merges_duplicate_field_evidence_before_resolution`

- fake 模型对同一个 `field_name` 返回两份 evidence。
- 确认 broad 节点会合并 `relevant_block_ids`、`evidence_texts`、`evidence_refs` 和 notes，避免多值字段因为 evidence 被拆条而整单失败。

`test_run_broad_extraction_rejects_unknown_fields_and_block_references`

- 第一段 fake 模型返回 schema 外字段。
- 第二段 fake 模型返回不存在的 `relevant_block_ids`。
- 确认 broad 校验会分别报错，保证字段集合和证据引用都可追踪。

`test_run_broad_extraction_rejects_evidence_refs_without_block_id`

- fake 模型返回的 `evidence_refs` 带有 `document_id/page`，但没有 `block_id`。
- 确认 broad 校验会在进入 resolution 前拒绝这类 ref，避免 trace 中出现无法稳定回查到输入 block 的证据位置。

## 运行方式

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
