# test_html_tools_new.py

这份测试覆盖抽取工具层的自由浏览和候选证据记录规则。工具围绕虚拟文件树工作：模型可见 locator 统一为 `evidence://...` link，工具内部再转回 canonical `path_id` selector。公开 `read` 工具只接收 `path_id`，一次只打开一个 paragraph/list/table 对象，不再暴露 `count/offset/limit` 这类连续读取或分页参数。`add_candidate_evidence` 通过显式 `evidence://` block link 把任意可读对象保存为字段候选 block evidence；字段写入必须基于同字段当前 `review_evidences` snapshot。

实现链路：

```text
documents + task_spec
  -> build_graph_input / build_graph_state
  -> tree(path_id="") 打开根目录，tree/read 使用 tree 输出里的 evidence:// locator 浏览材料
  -> 内部工具 helper 与模型工具 schema 都不接收 reason 参数
  -> read(evidence://...) 先校验 locator 指向可读 block，再只返回这个 block 的阅读视图
  -> read 成功后可以继续 tree/read/review，工具层不拦截下一步
  -> add_candidate_evidence(field_id, path_id) 显式保存一个字段和一个 evidence:// block link
  -> review_evidences(field_id) 把候选 block 展开成 inline evidence links 和 evidence_texts
  -> write_field 写入字段值和当前 review snapshot 里的 inline evidence links
  -> submit_result 做 schema 与 evidence 校验
  -> state.events 记录真实工具事件
```

## 测试函数

- `test_build_tools_exposes_candidate_tools_only`：确认公开工具集收口到 `tree/read/add_candidate_evidence/review_evidences/write_field/submit_result`。
- `test_module_exports_current_review_helper`：确认模块星号导出同步到当前 `_review_evidences` helper，不再暴露旧 `_anchors`、`_query_table`、`_review_field` 名称。
- `test_internal_tool_helpers_do_not_accept_reason_parameter`：确认内部工具 helper 也不再接收 `reason` 参数。
- `test_read_allows_free_navigation_after_successful_read`：确认 `read` 成功后可以继续 `tree/read`，不会再返回 `READ_JUDGEMENT_REQUIRED`。
- `test_tool_path_arguments_use_evidence_links_and_write_final_evidence_copies_review_links`：确认模型工具参数使用 `evidence://` block/inline links；根目录通过空 path_id 打开，文档目录显示为 `evidence://0001`；`add_candidate_evidence` 对模型返回候选 link，内部 state 仍保存 canonical `path_id` selector。
- `test_bare_path_ids_are_rejected_for_model_facing_path_arguments`：确认模型面向的 `read/add_candidate_evidence` 参数拒绝裸 `path_id`，必须传 `evidence://` link。
- `test_read_reads_one_block_and_exposes_only_path_id_argument`：确认模型可见 `read` schema 只暴露 `path_id` 参数，内部读取也只返回指定的单个 paragraph/list/table block。
- `test_add_candidate_evidence_accepts_one_explicit_path_id_and_review_expands_inline`：确认 `add_candidate_evidence` 必须拿到显式 `evidence://` block link，且一次只记录一个字段和一个 paragraph/list/table block；`review_evidences` 会把 paragraph block 展开成 Sxxx inline link 和反查文本。
- `test_add_candidate_evidence_can_add_after_other_tools_with_explicit_path_id`：确认 `add_candidate_evidence` 不依赖当前 read 状态，插入其它工具后仍可用显式 `evidence://` link 保存字段候选。
- `test_list_and_table_read_return_all_rows_and_review_expands_all_inline`：确认 list/table 默认完整读取，保存候选 block 后 `review_evidences` 展开全部 Ixxx/Rxxx。
- `test_write_field_requires_reviewed_inline_evidence_not_block_evidence`：确认字段写入需要同字段 review snapshot，且 `final_evidence` 只能使用 review 返回的 inline evidence link。
- `test_write_field_accepts_recent_review_snapshot_but_rejects_unreviewed_fields`：确认同字段 review 后即使插入其它工具也可以写入；没有自己 snapshot 的字段仍不能写。
- `test_add_candidate_after_review_invalidates_review_snapshot_for_that_field`：确认同字段 review 后如果继续添加候选，旧 review snapshot 会失效，必须重新 review 后才能写旧 inline evidence。
- `test_missing_and_null_enum_values_can_use_empty_evidence_after_review`：确认 missing 字段和 null enum variant 可以使用空证据，但也必须先有同字段 review snapshot。
- `test_write_field_normalizes_enum_value_json_string_from_tool_call`：确认 provider 把 enum value 作为 JSON 字符串传入时，`write_field` 会先解析成 enum object 再校验和保存。
- `test_submit_result_requires_final_evidence_for_resolved_non_null_values`：确认非 null enum variant 写入前必须先 review；最终 `submit_result` 仍会拒绝空最终证据。
- `test_read_write_reject_raw_paths_and_bare_ids_and_use_evidence_links_through_review`：确认模型工具层拒绝 raw path 和裸 `path_id`，`read`、review 展开和 `write_field` 都使用 tree 返回的 `evidence://` link。
