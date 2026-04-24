# `test_tools.py`

## 基本实现思路

`file_extraction_agent.impl.tools` 给 resolution 阶段提供内部辅助能力。

```text
resolution 传入 broad 阶段的 EvidenceCollection 或全量 blocks
  -> get_field_bundle(...) 按字段名读取其他字段 evidence
  -> lookup_blocks_for_field(...) 按字段名和 lookup_hints 扫描标准化 blocks
  -> 返回匹配 block 与 LookupRecord
  -> resolution 把 LookupRecord 挂到 FieldDecision.lookup_records
```

## 测什么

- `get_field_bundle(...)` 能按字段名返回 broad 阶段已有证据。
- `lookup_blocks_for_field(...)` 能根据 lookup hints 找回相关 block，并保留文档页码和 block id。

## 每个函数在干什么

`test_get_field_bundle_returns_named_broad_evidence`

- 构造一个只包含 `amount` 的 `EvidenceCollection`。
- 确认可命中字段返回原始 `FieldEvidence`，未知字段返回 `None`。

`test_lookup_blocks_for_field_uses_hints_and_keeps_refs`

- 构造一个无关 block 和一个包含“应付金额”的 block。
- 调用补查工具并限制 `top_k=1`。
- 确认返回的 `LookupRecord` 保留目标字段、block id、文档 id 和页码。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_tools.py -q
```
