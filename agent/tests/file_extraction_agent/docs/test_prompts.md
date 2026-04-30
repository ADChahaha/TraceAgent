# `test_prompts.py`

## 基本实现思路

`service.file_extraction_agent.impl.broad.prompts` 和 `impl.resolution.prompts` 分别负责两个阶段的 prompt 组装。

```text
GraphState + 当前字段
  -> broad prompt 提供字段定义、可搜索内容摘要、已有候选和工具结果
  -> resolution prompt 提供字段定义、候选池、已完成字段和工具结果
  -> 在 payload.tool_contract 中注入每个 action 的用途、入参、返回和约束
  -> search_grep 的 query 统一要求使用大写 OR 连接短关键词
  -> 按 RunOptions 裁剪示例段落和候选数量
  -> 输出 system + user messages，不让 resolution 直接读取完整 blocks
```

## 测什么

- broad prompt 会带上 task、字段定义、metadata、搜索索引摘要和候选池。
- broad 和 resolution prompt 都会暴露统一的 `search_grep` 搜索动作和精确工具契约。
- prompt 会明确要求 search query 使用 `term1 OR term2 OR term3` 固定格式。
- resolution prompt 会聚焦目标字段的候选池，不直接携带原始 blocks。
- prompt builder 会在 payload 中写入 `prompt_budget`，说明输入总量、实际携带量和被省略量。

## 每个函数在干什么

`test_build_broad_messages_focuses_on_field_and_search_contract`

- 构造一个字段和一个段落索引。
- 确认 broad prompt 明确要求 `BroadAction`、`search_grep` 和 `finish_broad`。
- 确认 system message 明确 `OR` 查询格式。
- 确认 payload 包含当前字段、metadata、可搜索内容摘要和 `tool_contract`。

`test_build_resolution_messages_includes_candidate_pool_and_prior_decisions`

- 为目标字段写入一个候选。
- 确认 resolution prompt 包含候选 `candidate_id/text`。
- 确认 resolution prompt 暴露 `search_grep` 和 `final_decision`。
- 确认 resolution prompt 带有 `tool_contract`，且 `final_decision` 被描述为唯一正常出口。
- 确认 resolution prompt 不包含完整 `blocks`。

`test_prompt_builders_apply_prompt_budget_limits`

- 调小 broad 的段落展示预算和 resolution 的候选展示预算。
- 确认 broad 只展示预算内文本，resolution 只展示预算内候选。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_prompts.py -q
```
