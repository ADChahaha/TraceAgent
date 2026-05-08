# test_html_tools_new.py

这份测试覆盖 resolution 阶段公开工具的内部实现。测试使用带稳定 HTML id 的小文档构造 `GraphState` 风格对象，直接调用 `_search_elements`、`_scan_document`、`_read_element`、`_read_section`、`_table_extraction`、`_set_field`、`_update_plan` 和 `_finish`，确认工具返回给模型和 replay 的内容可验证、可追踪；no-plan 模式下 `_update_plan` 内部函数保留兼容测试，但不再通过 `build_tools` 暴露给模型。

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
- `test_read_section_returns_section_content_and_table_refs_by_depth`：确认按标题读取合理大小的章节时会完整返回普通正文和全部列表项，同时对表格仍只返回带表名/行数/列名的引用，并按 depth 控制范围。
- `test_read_section_auto_scans_too_long_content_with_isolated_reader`：确认章节内容超过上限时，`read_section` 会在工具内部用同一个 section id 调用隔离 scoped reader，不返回整段 HTML，而是返回候选 block 证据并把候选 evidence id 标记为已观察。
- `test_read_section_too_long_returns_error_when_auto_scan_unavailable`：确认章节过长但没有配置 `document_scan_model` 时，`read_section` 返回 `ok=false` 和 `scan_error`，不会把未扫描到的 evidence 标记为已观察。
- `test_search_elements_returns_paragraphs_and_observes_evidence`：确认关键词搜索直接返回匹配元素 id、类型、可读 HTML、evidence ids 和文本长度，并写入 action trace，同时把匹配 id 标记为已观察 evidence。
- `test_search_elements_excludes_page_level_aggregate_text`：确认关键词搜索只返回段落、标题等 block 级证据，不返回 `page_001` 这类整页聚合文本，也不会把整页 id 标记为已观察 evidence。
- `test_search_elements_result_can_be_used_as_evidence`：确认搜索结果里的 evidence id 可以直接用于 `set_field`，模型只有在需要更多上下文时才需要额外 `read_element`。
- `test_scan_document_uses_isolated_model_on_scope_without_tools_and_observes_blocks`：确认隔离扫描模型只通过普通 `invoke` 读取指定 `scope_id` 下的完整内容，不绑定任何工具；传给 reader 的 scope 不包含下一个同级章节，返回结果会过滤 scope 外 id、整页聚合 id 和未知 id，只保留 scope 内 block 级候选证据并标记为已观察。
- `test_scan_document_result_can_be_used_as_evidence`：确认 `scan_document` 返回的候选 evidence id 可以直接用于 `set_field`。
- `test_scan_document_returns_error_without_scan_model`：确认未配置 `document_scan_model` 时，工具返回 `ok=false` 和明确错误，不会假装完成全文扫描。
- `test_scan_document_returns_error_for_unknown_scope_id`：确认 `scope_id` 不存在时工具直接返回明确错误，不会调用隔离 reader。
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
- `test_set_field_rejects_value_that_does_not_match_field_type`：确认 `set_field` 会在写入时立即校验字段值类型；如果 `list[string]` 字段收到字符串，会返回可重试的工具错误，并且不会污染 `field_states`。
- `test_update_plan_records_plan_status_and_action`：确认 `update_plan` 能按 `in_progress -> completed` 记录当前计划项状态，并写入 replay action。
- `test_update_plan_rejects_starting_later_plan_before_previous_completed`：确认模型不能跳过前面的 broad plan 直接把后面的 `plan_index` 标记为 `in_progress`。
- `test_update_plan_rejects_completing_plan_that_is_not_in_progress`：确认模型不能在某个 plan 没有先进入 `in_progress` 时直接标记 `completed`。
- `test_update_plan_rejects_invalid_plan_index`：确认越界的 `plan_index` 会返回明确错误。
- `test_set_field_rejects_unobserved_evidence_ids`：确认未通过读取或抽取工具观察到的 evidence id 不能用于 resolved 字段。
- `test_finish_fails_missing_required_field`：确认缺少必填字段时 `finish` 返回字段级错误。
- `test_build_tools_exposes_model_facing_docstrings_without_state_argument`：确认公开给模型的工具 schema 隐藏内部 `state`，不再暴露 `update_plan`，同时暴露必要参数和模型可读的工具说明，包括 `search_elements` 返回可读 HTML、`scan_document` 需要 `scope_id`、隔离无工具 reader 只扫描该 scope 下完整内容且只返回候选证据、`read_section` 太长时会自动调用隔离 scoped reader、evidence id 可直接用于 `set_field`，以及 table_extraction 的通用 query audit few-shot，要求模型根据表格上下文判断空白筛选行。
