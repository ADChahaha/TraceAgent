# `test_processor.py`

## 基本实现思路

`service.route_policy_agent.processor.evaluate(...)` 是 Python 业务入口，负责把外部输入串成字段级 route 判断：

```text
task_spec + field_outputs + refs_with_text + field_processes
  -> RoutePolicyInput 解析
  -> input_validator.validate_route_policy_input(...) 做字段名、refs 和过程摘要完整性校验
  -> mapper.build_field_policy_contexts(...) 合并单字段定义、输出、证据和过程摘要
  -> 如果字段定义声明 source_field/source_fields，把来源字段过程摘要作为 related_field_processes 放入 prompt
  -> required 且 allow_missing=false 的字段如果 failed、空值或缺少 field_output，直接 review，不调用模型
  -> resolved 但抽取过程摘要为空的字段直接 review，不调用模型
  -> query_audit/table_audit 作为工具事实观察进入 prompt，不用 status 硬判风险
  -> resolved 字段用 prompts.build_route_policy_messages(...) 构造只含字段、refs、field_process 和 related_field_processes 的评价上下文
  -> policy_client.invoke(RoutePolicyDecision, messages) 得到 accept/review/reject
  -> 对 task_spec 中缺席的 required 字段补 route=review
  -> 汇总 RoutePolicyResult(field_routes[])
```

## 测什么

- 模型判断 `accept` 时，字段 route 可自动放行。
- route policy prompt 会带上完整 `refs_with_text` 列表和每条完整 `text`，不做条数或字符数截断。
- 派生数量字段的 prompt 能看到来源列表字段的 search 查询词和过程摘要。
- 模型判断证据不足时，字段进入 `review`。
- resolved 字段如果抽取过程摘要为空，直接进入 `review`，不调用小 LLM。
- `query_audit.summary` 和 `table_audit.summary` 会进入小 LLM prompt，route policy 根据字段值、refs 和 `field_resolution.reason` 判断是否需要 review，prompt 不引导模型按非空数量分布做硬分类。
- system prompt 内置 query audit few-shot：空白筛选列必须结合表头、表注、分组标题、相邻列和 refs 判断；不能只因为空白行未被 WHERE 选中就说正常。
- required 字段抽取失败时直接 `review`，不调用小 LLM。
- required 字段完全缺少 `field_output` 时补一条 `review` route。
- required 字段值为空时直接 `review`，不调用小 LLM。
- 未显式传入 policy client 时，会把连接参数交给 client builder。

## 每个函数在干什么

`test_evaluate_accepts_resolved_field_when_policy_client_accepts`

- 用假的 policy client 返回 `accept`。
- 确认 processor 返回 `needs_review=False`。
- 确认 prompt 中包含字段值、refs 文本、`field_process.broad_extraction.search_queries` 和 `counted_fields` 摘要，但不包含工具返回结果。

`test_evaluate_keeps_complete_refs_with_text_in_policy_prompt`

- 构造 55 条 refs，其中第一条包含长文本和明确尾部标记。
- 确认传给小 LLM 的 user payload 保留全部 refs、长文本完整内容和最后一条 refs，防止 route policy prompt 再次静默截断证据。

`test_evaluate_includes_source_field_process_for_derived_count_field`

- 构造 `academic_paper_count` 指向 `academic_paper_names` 的 `source_field`。
- 来源列表字段使用 `type=list[string]`，和 file extraction 字段类型契约保持一致。
- 确认 system prompt 明确解释 `related_field_processes` 是来源字段过程摘要。
- 确认数量字段自己的 payload 里除了当前字段过程摘要，还包含来源字段 `academic_paper_names` 的 `related_field_processes`。
- 确认来源字段 broad 查过的 `学术论文 OR 论文题目 OR 作品类型` 会传给 route policy，但工具返回结果不会进入 prompt。

`test_evaluate_marks_resolved_field_for_review_when_evidence_is_insufficient`

- 用假的 policy client 返回 `review`。
- 确认 processor 保留模型给出的证据不足原因，并标记需要人工检查。

`test_evaluate_reviews_resolved_field_with_no_extraction_process_without_model_call`

- 构造 resolved 字段但 broad / resolution 过程摘要没有查询、候选、结束原因或定案 reason。
- 确认 processor 直接返回 `review`，route reason 指向抽取路径为空，不调用模型。

`test_evaluate_passes_query_audit_and_reason_to_policy_prompt`

- 构造 `query_audit.summary` 和 `field_resolution.reason`。
- 确认 processor 仍调用小 LLM，并且 prompt 中没有 `status`，由小 LLM结合查表摘要和模型解释判断。
- 确认 system prompt 包含 query audit few-shot，固定“空白筛选列必须结合表格上下文判断”和“不能只因为空白行未被 WHERE 选中就说正常”的判断样例。
- 确认 system prompt 不再要求模型查看非空数量分布，避免把工具事实变成按数量硬分类的规则。

`test_evaluate_passes_table_audit_summary_to_policy_prompt`

- 构造 `table_audit.summary`。
- 确认 processor 仍调用小 LLM，并把表格结构观察放进 prompt。

`test_evaluate_reviews_failed_required_field_without_model_call`

- 构造一个 failed 且 critical required 的字段。
- 确认 processor 直接返回 `review`，不会调用模型。

`test_evaluate_reviews_missing_required_field_output_without_model_call`

- 构造两个 required 字段，但只传入其中一个字段的 `field_output`。
- 确认已返回的字段正常进入 policy client，缺席字段会被补成 `review`。
- 确认缺席字段的 route reason 说明 file_extraction_agent 没有返回该字段。

`test_evaluate_reviews_empty_required_field_value_without_model_call`

- 构造 required 字段，状态是 resolved 但值为空字符串。
- 确认 processor 直接返回 `review`，不会调用模型。

`test_evaluate_builds_policy_client_when_not_provided`

- 不传 policy client，替换 builder。
- 确认 base_url、api_key、model 和结构化输出策略会被传入 builder。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/route_policy_agent/test_processor.py -q
```
