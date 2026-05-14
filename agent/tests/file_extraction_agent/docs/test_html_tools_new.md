# test_html_tools_new.py

这份测试覆盖新抽取工具层。工具围绕虚拟文件树工作，并在每次调用时写入流式事件；证据先通过 `bind_evidence` 使用 `path + sentences/items/rows` selector 绑定成候选 evidence。paragraph 证据必须先 `read` 同一路径，再紧跟 `anchors` 获取 Sxxx inline 句子编号；list/table 证据使用刚刚 `read` 或 `query_table` 暴露的 Ixxx/Rxxx 编号。同一个 inline 来源可以连续执行多个 `bind_evidence`；一旦插入非 `bind_evidence` 工具，旧 inline 来源就失效。只要某字段有候选 evidence，`write_field` 前就必须先 `review_field`，然后通过 `final_evidence` 提交筛选后的最终证据。

实现链路：

```text
documents + task_spec
  -> build_graph_input / build_graph_state
  -> tree/read/anchors/query_table 浏览材料
  -> read(.md) 后 anchors(.md) 获取 paragraph Sxxx，或 read/query_table 暴露 list/table Ixxx/Rxxx
  -> bind_evidence 立即绑定上一条 inline 来源里的字段候选证据 selector
  -> 有候选证据时 review_field 复看字段状态和证据文本
  -> write_field 写入可覆盖字段值和 final_evidence 定案
  -> submit_result 做 schema 与 evidence 校验
  -> state.events 记录真实工具事件
```

## 测试函数

- `test_build_tools_exposes_virtual_tree_tools_only`：确认模型只看到 `tree/read/anchors/query_table/bind_evidence/review_field/write_field/submit_result`，不再暴露 soft plan、旧 block 读取和 record note 工具。
- `test_tree_read_anchors_and_query_record_reasoned_events`：确认浏览、读取、句子编号和表格查询都会记录带 `reason` 的 started/completed 事件。
- `test_anchors_requires_immediate_prior_read_of_same_paragraph`：确认 `anchors` 只能紧跟同一路径 paragraph 的成功 `read`，不能在未读、读错路径或被其他工具打断后继续取 Sxxx inline 编号。
- `test_bind_evidence_requires_fresh_inline_source_from_previous_read_or_anchors`：确认 `bind_evidence` 只能使用上一条 inline-producing 结果里的 selector；paragraph 走 `read -> anchors -> bind_evidence`，list/table 可以使用刚 `read` 或 `query_table` 暴露的编号；同一 inline 来源允许连续多次绑定，但被 `tree/read/review/write` 等非 bind 工具打断后不能继续复用。
- `test_virtual_tree_tools_accept_percent_encoded_paths_and_return_canonical_paths`：确认模型把虚拟路径中的空格、中文或符号写成 URL percent-encoded 形式时，`tree/read/anchors/query_table/bind_evidence/write_field` 仍能命中节点，并在返回值和结果 evidence 中保存 canonical raw path。
- `test_bind_evidence_accumulates_selectors_and_write_field_submits_value`：确认同一字段可以先多次绑定候选 evidence selector，复看后再提交或覆盖字段值；成功绑定会附带系统反查的 `evidence_texts`，错误 selector 会返回失败且不污染字段结果。
- `test_write_field_requires_review_and_filters_final_evidence`：确认只要字段有候选 evidence，就必须先 `review_field` 再写；`write_field` 的 `final_evidence` 只能从该字段已绑定候选里选择，不能凭空提交未绑定 selector。
- `test_write_field_without_candidate_evidence_does_not_require_review`：确认字段没有候选 evidence 且 `final_evidence=[]` 时，可以直接写入缺失状态，不需要为了空证据调用 `review_field`。
- `test_submit_result_requires_final_evidence_for_resolved_non_null_values`：确认 `write_field` 可以先写入草稿，但 `submit_result` 会拒绝非 `null` resolved 字段空 `final_evidence`，避免模型无证据直接完成最终提交。
- `test_submit_result_allows_empty_final_evidence_for_null_enum_variant_only`：确认非 `null` enum variant 空证据会在 `submit_result` 被拒绝，而 `null` enum variant 可以用空 `final_evidence` 表示未提及。
- `test_review_field_returns_current_value_description_and_bound_evidence`：确认 `review_field` 只读返回字段描述、当前字段值、已绑定 evidence 和反查文本；未知字段返回结构化错误。
- `test_submit_result_validates_required_fields_and_returns_new_field_shape`：确认 `submit_result` 校验必填字段、类型和 evidence，并返回字段对象数组的新结果形态。
