# `test_input_validator.py`

## 基本实现思路

`input_validator` 负责跨对象协议一致性校验，把 schema 层已经解析出的对象整理成后续 mapper 可直接使用的索引：

```text
RoutePolicyInput(task_spec + field_outputs + refs_with_text)
  -> 建立 task_spec.fields 的 field_name 索引
  -> 校验每个 field_output.field_name 都存在于任务字段定义
  -> 校验每个待评估字段都有对应 FieldRefsWithText
  -> 校验 resolved 字段至少有一条 ref，且每条 ref 有 text 和来源位置
  -> 返回 ValidatedPolicyInput(field_definitions_by_name / field_outputs_by_name / refs_by_field_name)
```

## 测什么

- 合法输入会生成字段定义、字段输出和 refs 索引。
- 未知字段输出会被拒绝。
- 每个待评估字段必须有 refs 分组。
- ref 缺少证据文本会被拒绝。
- ref 没有任何来源位置会被拒绝。

## 每个函数在干什么

`test_validate_route_policy_input_builds_field_indexes`

- 输入一个合法字段和一条证据 ref。
- 确认 validator 返回后能按 `invoice_no` 直接取到定义、输出和值。

`test_validate_route_policy_input_rejects_unknown_field_output`

- 把字段输出改成任务定义里不存在的 `unknown`。
- 确认错误信息指出未知字段名。

`test_validate_route_policy_input_requires_refs_group_for_every_field_output`

- 删除 `refs_with_text` 分组。
- 确认每个待评估字段都必须带 refs 分组。

`test_validate_route_policy_input_rejects_resolved_field_without_ref_text`

- 给 resolved 字段传一条空白证据文本。
- 确认 validator 指出具体字段和 ref 下标。

`test_validate_route_policy_input_rejects_ref_without_source_location`

- 只传证据文本、不传 document/page/block/span。
- 确认 validator 要求 ref 具备来源位置。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/route_policy_agent/test_input_validator.py -q
```
