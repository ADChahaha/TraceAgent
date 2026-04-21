# `test_prompts.py`

## 基本实现思路

`file_extraction_agent.impl.prompts` 负责把内部已经确定好的 `GraphInput`、字段定义和 broad extraction 结果，组装成给模型调用层消费的消息列表。它不负责真正调用模型，也不负责字段定案；它只负责把结构化上下文压成稳定、可重复的 prompt 输入。

这一层按下面的 pipeline 理解：

```text
GraphInput 或 broad_output
  -> 提取 session_id、task_name、documents、field 定义
  -> 按阶段选择 broad extraction 或 field resolution 的系统指令
  -> 把目标字段、候选值、交叉字段摘要等上下文序列化成 JSON
  -> 返回给 extractor client 的 messages 列表
```

## 测什么

- broad extraction prompt 会带上 session、task、字段定义和文档摘要
- field resolution prompt 会聚焦目标字段，并同时保留全局字段候选上下文

## 每个函数在干什么

`test_build_broad_extraction_messages_includes_session_task_and_documents_summary`

- 构造一份最小可用的 `GraphInput`。
- 调用 `build_broad_extraction_messages(...)`。
- 确认 broad extraction 阶段的消息里包含 session、task、metadata、字段定义和文档摘要。

`test_build_field_resolution_messages_focuses_on_target_field_and_candidates`

- 构造 `GraphInput` 和一份包含多个字段候选的 `BroadExtractionOutput`。
- 调用 `build_field_resolution_messages(...)`，目标字段指定为 `amount`。
- 确认 resolution 阶段的消息会把目标字段候选单独展开，同时保留全局字段输出摘要。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_prompts.py -q
```
