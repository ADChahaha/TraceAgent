# `test_broad_extraction.py`

## 基本实现思路

这个测试文件约束 `file_extraction_agent.impl.broad_extraction` 的第一阶段节点行为。

```text
GraphState(extraction_input=..., evidence_collection=None)
  -> run_broad_extraction(...) 读取 state.extraction_input
  -> build_broad_extraction_messages(extraction_input)
  -> extractor_client.invoke(output_schema=EvidenceCollection, messages=...)
  -> 校验 EvidenceCollection 覆盖 task_spec 中的所有字段
  -> 校验 broad 没有返回重复字段或 schema 外字段
  -> 校验 relevant_block_ids / evidence_refs.block_id 都来自输入 blocks
  -> 将返回的 EvidenceCollection 写入 state.evidence_collection
```

## 覆盖点

- 节点会请求 `EvidenceCollection`
- 节点会拒绝缺失字段、重复字段和 schema 外字段
- 节点会拒绝 broad 引用不存在的 block id
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

`test_run_broad_extraction_rejects_duplicate_fields_before_resolution`

- fake 模型对同一个 `field_name` 返回两份 evidence。
- 确认 broad 校验会拒绝重复字段，避免后续定案阶段拿到含糊 bundle。

`test_run_broad_extraction_rejects_unknown_fields_and_block_references`

- 第一段 fake 模型返回 schema 外字段。
- 第二段 fake 模型返回不存在的 `relevant_block_ids`。
- 确认 broad 校验会分别报错，保证字段集合和证据引用都可追踪。

## 运行方式

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_broad_extraction.py -q
```
