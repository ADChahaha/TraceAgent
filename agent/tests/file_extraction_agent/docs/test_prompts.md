# `test_prompts.py`

## 基本实现思路

`file_extraction_agent.impl.prompts` 负责把内部 `ExtractionInput` 和 `EvidenceCollection` 组装成给模型调用层消费的消息列表。

```text
ExtractionInput 或 EvidenceCollection
  -> 提取 task_name、blocks、field 定义
  -> broad prompt 要求模型返回字段级 evidence，并按 validation_rules 筛选最小证据片段
  -> resolution prompt 聚焦目标字段 evidence，同时要求最终值满足 validation_rules
  -> 返回给 ExtractorClient 的 messages 列表
```

## 测什么

- broad prompt 会带上 task、字段定义和 blocks 摘要
- broad prompt 会提示模型使用 `validation_rules` 的 filter/exclude/target_column 约束 evidence
- resolution prompt 会聚焦目标字段，并保留全局字段 evidence 上下文
- resolution prompt 会提示模型最终值必须满足 `validation_rules`，且不能混入 exclude 命中的证据

## 每个函数在干什么

`test_build_broad_extraction_messages_includes_task_and_blocks_summary`

- 构造一份最小可用的 `ExtractionInput`。
- 确认 broad prompt 里包含 task、metadata、字段定义和 blocks 摘要。
- 确认 broad prompt 的系统消息明确提到 `validation_rules`。

`test_build_field_resolution_messages_focuses_on_target_field_and_evidence`

- 构造 `ExtractionInput` 和一份多字段 `EvidenceCollection`。
- 确认 resolution prompt 会单独展开目标字段 evidence，同时保留全量字段 evidence 摘要。
- 确认 resolution prompt 的系统消息明确提到 `validation_rules`。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_prompts.py -q
```
