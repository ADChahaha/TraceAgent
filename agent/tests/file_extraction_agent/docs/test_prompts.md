# `test_prompts.py`

## 基本实现思路

`file_extraction_agent.impl.prompts` 负责把内部已经确定好的 `GraphInput`、字段定义和 broad extraction 结果，组装成给模型调用层消费的消息列表。它不负责真正调用模型，也不负责字段定案；它只负责把 blocks 主输入和字段上下文压成稳定、可重复的 prompt 输入。

这一层按下面的 pipeline 理解：

```text
GraphInput 或 broad_output
  -> 提取 task_name、blocks、field 定义
  -> broad prompt 要求模型返回字段级 evidence bundle
  -> resolution prompt 聚焦目标字段 evidence bundle，同时保留全字段输出摘要
  -> 返回给 extractor client 的 messages 列表
```

## 测什么

- broad extraction prompt 会带上 task、字段定义和 blocks 摘要
- field resolution prompt 会聚焦目标字段，并保留全局字段 evidence bundle 上下文

## 每个函数在干什么

`test_build_broad_extraction_messages_includes_task_and_blocks_summary`

- 构造一份最小可用的 `GraphInput`。
- 调用 `build_broad_extraction_messages(...)`。
- 确认 broad extraction 阶段的消息里包含 task、metadata、字段定义和 blocks 摘要。

`test_build_field_resolution_messages_focuses_on_target_field_and_evidence_bundle`

- 构造 `GraphInput` 和一份包含多个字段 evidence bundle 的 `BroadExtractionOutput`。
- 调用 `build_field_resolution_messages(...)`，目标字段指定为 `amount`。
- 确认 resolution 阶段的消息会把目标字段 evidence bundle 单独展开，同时保留全量 blocks 和全局字段输出摘要。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_prompts.py -q
```
