# `test_tools.py`

## 基本实现思路

`service.file_extraction_agent.impl.tools` 拆成确定性搜索和候选池读写能力。

```text
GraphState
  -> search_grep(...) 同时检索 paragraph_index 和 table_row_index
  -> 只将 "A OR B" 这类大写 OR query 拆成多个关键词，任一命中即可返回
  -> 兼容 search_text_grep(...) / search_table_rows_grep(...) 的旧入口
  -> add_broad_candidate(...) / add_resolution_candidate(...) 将 ref 写入候选池
  -> get_candidate_bundle(...) 按字段读取 candidate_id/text 摘要
  -> 每个工具动作都写入 state.actions[field_name]
```

## 测什么

- text grep 返回 paragraph 级 `ref/text` 并记录 `text_grep`。
- table grep 只返回命中的行级 `ref/text`，不会把整张表交给模型。
- 统一 search grep 同时搜索正文和表格行，并只把大写 `OR` query 拆成多个命中词。
- 中文“或”、逗号、顿号等格式不会被当作多词分隔。
- 候选工具能写入、去重、读取候选，并区分 broad/resolution 来源。

## 每个函数在干什么

`test_search_text_grep_returns_paragraph_refs_and_records_action`

- 构造包含金额段落的状态。
- 搜索“应付金额”，确认返回 `b-text:p:p1` 和完整段落文本。
- 确认动作记录进入当前字段 trace。

`test_search_table_rows_grep_returns_only_matching_row_refs`

- 构造两行表格，一行 selected、一行 rejected。
- 搜索 selected，确认只返回 selected 行。

`test_search_grep_searches_text_and_table_rows_with_or_query`

- 构造正文和表格共存的状态。
- 用 `应付金额 OR selected` 搜索，确认正文段落和表格行都会返回。
- 确认 trace 记录统一的 `search_grep` 动作和拆分后的 `query_terms`。

`test_search_grep_only_splits_terms_with_uppercase_or_format`

- 用 `应付金额 或 selected` 搜索。
- 确认工具不会把中文“或”当成分隔符，`query_terms` 保留原始字符串。

`test_candidate_tools_add_dedupe_and_read_field_candidates`

- 先写入 broad 候选，再重复写入同一 ref。
- 再写入 resolution 候选并读取候选池。
- 确认重复 ref 复用原 candidate id，候选读取也记录为动作。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_tools.py -q
```
