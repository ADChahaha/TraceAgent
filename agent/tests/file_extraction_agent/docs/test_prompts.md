# `test_prompts.py`

## 基本实现思路

`service.file_extraction_agent.impl.prompts` 负责把内部 `ExtractionInput` 和 `EvidenceCollection` 组装成给模型调用层消费的消息列表。

```text
ExtractionInput 或 EvidenceCollection
  -> 提取 task_name、blocks、field 定义
  -> 使用 block.block_id 作为 prompt 和 trace 可引用的唯一 id
  -> broad prompt 要求模型返回字段级 evidence，并按 validation_rules 筛选最小证据片段
  -> broad prompt 按 RunOptions 的 prompt budget 限制 blocks 数量和单块文本长度
  -> resolution prompt 聚焦目标字段 evidence 和全字段 evidence 摘要，不直接携带原始 blocks
  -> resolution prompt 按 RunOptions 限制字段 evidence 数量和 evidence 文本长度
  -> 如果已有 tool evidence / records，就一并放入下一轮 resolution prompt
  -> 返回给 ExtractorClient 的 messages 列表
```

## 测什么

- broad prompt 会带上 task、字段定义和 blocks 摘要
- broad prompt 中的 blocks 使用上游显式传入的 `block_id`
- broad prompt 会提示模型使用 `validation_rules` 的 filter/exclude/target_column 约束 evidence
- resolution prompt 会聚焦目标字段，并保留全局字段 evidence 上下文
- resolution prompt 不直接携带原始 blocks，原始 blocks 只能由 lookup 工具按需访问
- resolution prompt 会要求模型返回 `FieldResolutionAction`，可选择最终定案或请求工具
- resolution prompt 会带上 `tool_evidence` 和 `tool_records`，用于工具调用后的下一轮模型定案
- resolution prompt 会提示模型最终值必须满足 `validation_rules`，且不能混入 exclude 命中的证据
- prompt builder 会在 payload 中写入 `prompt_budget`，说明输入总量、实际携带量和被省略量

## 每个函数在干什么

`test_build_broad_extraction_messages_includes_task_and_blocks_summary`

- 构造一份最小可用的 `ExtractionInput`。
- 确认 broad prompt 里包含 task、metadata、字段定义和 blocks 摘要。
- 确认 broad prompt 的系统消息明确提到 `validation_rules`。

`test_build_field_resolution_messages_focuses_on_target_field_and_evidence`

- 构造 `ExtractionInput` 和一份多字段 `EvidenceCollection`。
- 确认 resolution prompt 会单独展开目标字段 evidence，同时保留全量字段 evidence 摘要。
- 确认 resolution prompt 的系统消息明确要求 `FieldResolutionAction`，并包含 `lookup_blocks` 工具动作。
- 确认默认会传入空的 `tool_evidence` 和 `tool_records`，给工具后续轮次复用。
- 确认 resolution prompt 不会直接带入原始 `blocks`，避免模型绕过 lookup trace 直接回查全文。

`test_prompt_builders_apply_prompt_budget_limits`

- 构造带两个 blocks、两个字段 evidence 的输入，并把 prompt budget 调小。
- 确认 broad prompt 只携带预算内 blocks，且 block 文本按字符上限截断。
- 确认 resolution prompt 优先保留目标字段 evidence，并记录被省略的字段 evidence 数量。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_prompts.py -q
```
