# test_html_tools_new.py

这份测试覆盖 resolution 阶段 HTML 工具的内部实现和模型可见 schema。测试用带稳定 HTML id 的小文档构造 `GraphState` 风格对象，直接调用工具内部函数，确认返回内容、证据标记、字段写入和 replay action 都可验证。

实现链路：

```text
测试 HTML
  -> build_html_document 建立 elements_by_id、tables_by_id 和 row_index
  -> 直接调用 _overview / _read_* / _query_table / _preview_inline_evidence / _set_field 等内部函数
  -> 校验工具返回、observed_evidence_ids、field_states 和 actions
  -> 错误路径返回 ok=false 或 errors，供模型修正参数后重试
```

## 测试函数

- `test_overview_returns_document_tree`：确认 overview 返回 heading 摘要但不把平级 block 算进前一个 heading，并写入 action trace。
- `test_overview_exposes_mixed_dom_items_in_dom_order`：确认 overview 按 DOM 顺序暴露 `section`、heading、`p`、table、list 等同层项；顶层 table 标为 `query_table + block_offset=0`，顶层 list 标为 `read_list + block_offset=0`。
- `test_read_element_returns_text_element`：确认读取普通文本元素会返回紧凑 HTML、元素类型和自身 evidence id。
- `test_read_element_table_returns_header_only`：确认读取表格元素只返回 `table-ref`、表名、表头列和行数，不返回数据行；SQL 提示只使用通用占位列名，不含任务特化示例。
- `test_read_section_does_not_read_sibling_blocks`：确认 `read_section` 不会把 heading 后面的平级段落、列表或表格当作该 heading 的 block。
- `test_read_blocks_reads_leaf_block_by_selected_index`：确认 overview 暴露的叶子文本块可以用 `read_blocks(block_id, indexes=[0])` 直接读取并标记证据。
- `test_read_blocks_returns_list_and_table_refs_without_expanding_rows`：确认 list/table block 通过 `read_blocks` 返回 ref，不直接展开全部 list items 或 table rows。
- `test_read_blocks_supports_section_scopes_and_leaf_block_ids`：确认 `read_blocks` 既支持 section 容器索引，也支持段落这类叶子块 id 的单块读取。
- `test_read_blocks_reads_non_contiguous_selected_indexes`：确认 `read_blocks(indexes=[...])` 会按模型给出的离散 index 精确读取，不把首尾之间的块自动展开成连续窗口。
- `test_read_block_range_reads_contiguous_window`：确认 `read_block_range(start_index, count)` 会从同一 scope 中连续读取一段 block，并把实际读取的 indexes、证据 id 和 trace action 记录清楚。
- `test_read_block_range_rejects_invalid_range_arguments`：确认连续读取工具会拒绝负数 start、非正 count 和越界 start，并记录可回放的错误 action。
- `test_read_blocks_rejects_invalid_indexes`：确认 `read_blocks` 对空 index 列表、负数、越界和非整数 index 返回清晰错误，并记录 trace action。
- `test_read_list_paginates_list_items`：确认 `read_list(section_id, block_offset, ...)` 能按 list item offset 分页读取列表项。
- `test_read_list_uses_leaf_list_id_with_zero_offset`：确认 overview 暴露的顶层 list id 可以直接作为 `read_list` 的 scope，并用 `block_offset=0` 读取列表项。
- `test_search_elements_returns_paragraphs_and_observes_evidence`：确认关键词搜索返回匹配元素、可读 HTML、证据 id 和文本长度，并标记证据。
- `test_search_elements_excludes_page_level_aggregate_text`：确认关键词搜索不会返回整页聚合文本作为证据。
- `test_search_elements_result_can_be_used_as_evidence`：确认搜索观察到文本块后，还需要通过 `preview_inline_evidence` 生成 inline 级证据，才能用于 `set_field`。
- `test_scan_document_uses_isolated_model_on_scope_without_tools_and_observes_blocks`：确认 scoped reader 只读取指定 scope，不绑定工具，并过滤 scope 外、未知或整页聚合 id。
- `test_scan_document_result_can_be_used_as_evidence`：确认 scoped reader 返回候选文本块后，需要先预览 inline 证据再写字段。
- `test_scan_document_returns_error_without_scan_model`：确认未配置隔离 reader 时返回明确错误。
- `test_scan_document_returns_error_for_unknown_scope_id`：确认 scope id 不存在时不调用 reader，并返回明确错误。
- `test_table_extraction_selects_rows_with_evidence_ids`：确认 SQL 查询表格会返回匹配行、值和 `table_id + row_id` 证据。
- `test_query_table_uses_section_block_offset_for_sql`：确认 `query_table(section_id, block_offset, sql)` 能通过章节块 offset 定位表格。
- `test_query_table_uses_leaf_table_id_with_zero_offset`：确认 overview 暴露的顶层 table id 可以直接配 `block_offset=0` 查询。
- `test_table_extraction_all_columns_allowed_for_small_tables`：确认小表允许 `SELECT *` 返回全部列和匹配行。
- `test_table_extraction_rejects_select_star_for_large_tables`：确认大表裸 `SELECT *` 会被拒绝，并返回分页或选择必要列的提示。
- `test_table_extraction_large_tables_allow_select_star_with_bounded_limit`：确认大表允许带 `LIMIT 50` 以内的 `SELECT *` 分页读取。
- `test_table_extraction_large_tables_reject_select_star_above_limit`：确认大表 `SELECT *` 的分页上限为 50 行。
- `test_table_extraction_large_tables_allow_specific_columns_without_truncating_rows`：确认大表选择具体列时不会按行数截断。
- `test_table_extraction_reports_table_audit_for_empty_cells`：确认表格空 cell 会进入轻量 `table_audit.blank_cells`，并按列返回空值数量和空值行 id。
- `test_table_extraction_table_audit_keeps_first_ten_blank_row_ids_without_truncated_label`：确认空值行 id 最多保留前 10 个，且不额外返回 truncated 标记。
- `test_table_extraction_returns_summary_without_query_audit`：确认 `query_table` 不再返回详细 `query_audit`，而是用顶层 `summary` 描述本次查询返回行数和输出列空值数量。
- `test_table_extraction_summary_summarizes_selected_output_empty_cells_without_warning`：确认稀疏标签列只生成查询事实摘要，不输出硬编码风险状态。
- `test_table_extraction_returns_lightweight_audit_without_status`：确认轻量表格审计不携带诊断状态字段。
- `test_table_extraction_row_evidence_ids_can_be_used_by_set_field`：确认表格查询观察到的行证据可以用于字段写入。
- `test_preview_inline_evidence_returns_sentence_candidates_and_observes_inline_ids`：确认已读取文本块可以被切成 inline 候选证据，并把生成的 inline id 标记为已观察。
- `test_preview_inline_evidence_keeps_long_sentence_as_one_inline_candidate`：确认长合同句不会再按固定字符数二次截断，避免证据锚点切断定义或条款。
- `test_preview_inline_evidence_requires_observed_text_source`：确认 inline 预览只能针对已观察的文本类元素，表格和列表必须分别走 `query_table` 和 `read_list`。
- `test_set_field_requires_inline_evidence_for_text_blocks`：确认 resolved 字段不能直接使用整段文本块 id，必须使用 `preview_inline_evidence` 返回的 inline id。
- `test_set_field_requires_row_or_item_level_evidence_for_tables_and_lists`：确认 resolved 字段不能只使用 table/list 容器 id，表格必须包含行 id，列表必须包含 item id。
- `test_table_extraction_returns_sql_errors_for_model_retry`：确认 SQL 错误返回可重试信息、可用列名和通用双引号提示，且提示不含任务特化 SQL 示例。
- `test_paragraph_extraction_returns_all_regex_matches`：确认段落正则抽取返回所有匹配文本及对应证据。
- `test_set_field_records_value_and_finish_validates_required_fields`：确认字段写入后保存值和证据，必填字段齐全时 `finish` 成功。
- `test_set_field_rejects_value_that_does_not_match_field_type`：确认字段值类型不匹配时返回错误且不污染 `field_states`。
- `test_update_plan_records_plan_status_and_action`：确认计划状态可按 `in_progress -> completed` 写入并进入 replay action。
- `test_update_plan_rejects_starting_later_plan_before_previous_completed`：确认计划步骤不能跳过前面的未完成项。
- `test_update_plan_rejects_completing_plan_that_is_not_in_progress`：确认计划步骤必须先进入 `in_progress` 才能完成。
- `test_update_plan_rejects_invalid_plan_index`：确认越界计划索引返回明确错误。
- `test_set_field_rejects_unobserved_evidence_ids`：确认未被读取或查询观察到的 evidence id 不能用于 resolved 字段。
- `test_finish_fails_missing_required_field`：确认缺少必填字段时 `finish` 返回字段级错误。
- `test_build_tools_exposes_model_facing_docstrings_without_state_argument`：确认模型可见工具 schema 隐藏内部 `state`，`read_blocks` 暴露 `indexes` 而不暴露旧的 `offset/number`，`read_block_range` 暴露 `start_index/count`，并在说明中暴露 section/leaf block、顶层 list id、顶层 table id、`block_offset=0`、`preview_inline_evidence` 和证据写入约束。
