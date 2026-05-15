# test_html_tools_new.py

这份测试覆盖新抽取工具层的 read 后强制判断状态机。工具围绕虚拟文件树工作：`read` 只负责打开一个 paragraph/list/table 对象；成功读取后必须立刻用 `bind_evidence` 把当前对象作为字段候选 block evidence，或用 `skip_read` 标记当前对象完全无关。字段写入前必须调用 `review_evidences`，由工具把候选 block 展开成 Sxxx/Ixxx/Rxxx inline selector；`write_field(final_evidence=...)` 只能使用这些 review 返回的 inline selector，不能直接写 block selector。

实现链路：

```text
documents + task_spec
  -> build_graph_input / build_graph_state
  -> tree/read 使用 path_id 浏览材料
  -> read 成功后 pending_read 记录当前对象
  -> bind_evidence(field_id) 绑定当前对象 block，或 skip_read() 关闭无关对象
  -> review_evidences(field_id) 把候选 block 展开成 inline selector 和 evidence_texts
  -> write_field 写入字段值和已 review 的 inline final_evidence
  -> submit_result 做 schema 与 evidence 校验
  -> state.events 记录真实工具事件
```

## 测试函数

- `test_build_tools_exposes_read_judgement_tools_only`：确认公开工具集收口到 `tree/read/bind_evidence/skip_read/review_evidences/write_field/submit_result`。
- `test_module_exports_current_review_helper`：确认模块星号导出同步到当前 `_review_evidences` helper，不再暴露旧 `_anchors`、`_query_table`、`_review_field` 名称。
- `test_read_requires_bind_or_skip_before_other_tools`：确认 `read` 成功后必须先 `bind_evidence` 或 `skip_read`，否则继续 `tree/read` 会返回 `READ_JUDGEMENT_REQUIRED`。
- `test_bind_evidence_uses_current_read_block_and_review_expands_inline`：确认 `bind_evidence` 只使用当前 pending read block，连续 bind 可以把同一对象绑定到多个字段；`review_evidences` 会把 paragraph block 展开成 Sxxx inline selector 和反查文本。
- `test_bind_evidence_cannot_reuse_read_after_other_tool`：确认一旦插入非 bind 工具，就不能回头把旧 read block 绑定给字段。
- `test_list_and_table_read_return_all_rows_and_review_expands_all_inline`：确认 list/table 默认完整读取，绑定 block 后 `review_evidences` 展开全部 Ixxx/Rxxx。
- `test_write_field_requires_reviewed_inline_evidence_not_block_evidence`：确认 resolved 非 null 字段写入必须先 review，且 `final_evidence` 只能使用 review 返回的 inline selector，不能使用 block selector 或未 review 的编号。
- `test_missing_and_null_enum_values_can_use_empty_evidence_without_review`：确认 missing 字段和 null enum variant 可以空证据写入，不需要为了空证据 review。
- `test_submit_result_requires_final_evidence_for_resolved_non_null_values`：确认非 null enum variant 写入前必须先 review；即使 review 后可以先写空证据草稿，最终 `submit_result` 仍会拒绝空最终证据。
- `test_read_write_reject_raw_paths_and_use_path_id_through_review`：确认模型工具层拒绝 raw path，`read`、review 展开和 `write_field` 都使用 tree 返回的 `path_id` selector。
