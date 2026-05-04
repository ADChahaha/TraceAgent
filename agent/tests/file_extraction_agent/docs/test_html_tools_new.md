# test_html_tools_new.py

这份测试覆盖 resolution 阶段公开工具的内部实现。测试使用带稳定 HTML id 的小文档构造 `GraphState` 风格对象，直接调用 `_read_element`、`_read_section`、`_table_extraction`、`_set_field`、`_update_plan` 和 `_finish`，确认工具返回给模型和 replay 的内容可验证、可追踪。

实现链路：

```text
测试 HTML
  -> build_html_document 建立元素、表格和行索引
  -> 调用单个工具内部函数
  -> 校验返回值、observed_evidence_ids、field_states 或 actions
  -> 对错误路径校验 ok=false 和可供模型重试的错误信息
```

## 测试函数

- `test_overview_returns_document_tree`：确认 overview 返回文档树，表格节点只暴露表名、列名和数据行数，不把完整正文行塞进 overview。
- `test_read_element_returns_text_element`：确认读取普通文本元素会返回紧凑 HTML、元素类型和自身 evidence id。
- `test_read_element_table_returns_header_only`：确认读取表格时只返回 `table-ref`、表名、表头列和行数，不返回表格数据行。
- `test_read_section_returns_section_content_and_table_refs_by_depth`：确认按标题读取章节时会包含直接内容、子标题、列表摘要和带表名/行数/列名的表格引用，并按 depth 控制范围。
- `test_table_extraction_selects_rows_with_evidence_ids`：确认 SQL 查询表格会返回匹配行的值、`row_id` 和由 `table_id + row_id` 组成的 evidence ids。
- `test_table_extraction_all_columns_allowed_for_small_tables`：确认小表可以使用 `SELECT *` 读取全部列和全部匹配行。
- `test_table_extraction_rejects_select_star_for_large_tables`：确认大表裸 `SELECT *` 会被拒绝，并返回改用必要列或 `LIMIT 50` 分页的提示。
- `test_table_extraction_large_tables_allow_select_star_with_bounded_limit`：确认大表在表格混乱、必须看全列时，可以用 `SELECT * FROM data LIMIT 50 OFFSET ...` 分页读取。
- `test_table_extraction_large_tables_reject_select_star_above_limit`：确认大表 `SELECT *` 的分页上限是 50 行，超过上限仍会被拒绝。
- `test_table_extraction_large_tables_allow_specific_columns_without_truncating_rows`：确认大表选择具体列时不会按行数截断，工具会返回 SQL 匹配的全部行。
- `test_table_extraction_reports_table_audit_for_empty_cells`：确认表格存在空 cell 时会返回 `table_audit.blank_cells`，让模型和人工看到整表解析事实，但不提前给出风险状态。
- `test_table_extraction_reports_query_audit_for_possible_missed_rows`：确认当前 SQL 查询会返回 `query_audit.predicate_columns`，记录筛选列空白行和近似未选中行等事实观察。
- `test_table_extraction_query_audit_summarizes_sparse_label_column_without_warning`：确认稀疏标签列会生成自然语言 `query_audit.summary`，但不会把空白分类列硬编码为 warning，也不会输出按非空值数量分布做出的分类提示。
- `test_table_extraction_returns_audit_without_status`：确认工具结果返回 `query_audit`，且不会携带诊断状态字段。
- `test_table_extraction_row_evidence_ids_can_be_used_by_set_field`：确认 `table_extraction` 观察到的行证据可以立刻用于 `set_field` 写字段。
- `test_table_extraction_returns_sql_errors_for_model_retry`：确认 SQL 写错时工具返回 `ok=false`、原始错误、可用列名和双引号提示，方便模型修正后重试。
- `test_paragraph_extraction_returns_all_regex_matches`：确认段落正则抽取会返回所有匹配文本及对应 evidence id。
- `test_set_field_records_value_and_finish_validates_required_fields`：确认字段写入后会保存值和证据，且必填字段齐全时 `finish` 成功。
- `test_update_plan_records_plan_status_and_action`：确认 `update_plan` 能按 `in_progress -> completed` 记录当前计划项状态，并写入 replay action。
- `test_update_plan_rejects_starting_later_plan_before_previous_completed`：确认模型不能跳过前面的 broad plan 直接把后面的 `plan_index` 标记为 `in_progress`。
- `test_update_plan_rejects_completing_plan_that_is_not_in_progress`：确认模型不能在某个 plan 没有先进入 `in_progress` 时直接标记 `completed`。
- `test_update_plan_rejects_invalid_plan_index`：确认越界的 `plan_index` 会返回明确错误。
- `test_set_field_rejects_unobserved_evidence_ids`：确认未通过读取或抽取工具观察到的 evidence id 不能用于 resolved 字段。
- `test_finish_fails_missing_required_field`：确认缺少必填字段时 `finish` 返回字段级错误。
- `test_build_tools_exposes_model_facing_docstrings_without_state_argument`：确认公开给模型的工具 schema 隐藏内部 `state`，同时暴露必要参数和模型可读的工具说明，包括 table_extraction 的通用 query audit few-shot，要求模型根据表格上下文判断空白筛选行。
