# `test_validation.py`

## 基本实现思路

`service.file_extraction_agent.impl.validation` 负责模型完成字段定案之后的确定性后处理。

```text
FieldDecision + FieldDefinition + GraphState
  -> apply_validation_rules(...)
  -> 按 validation_rules 做通用规则覆盖或跨字段一致性收口
  -> apply_field_constraints(...)
  -> 按 required / enum_values / type 做基础字段约束校验
  -> 返回校正后或降级后的 FieldDecision
```

这个测试文件固定 validation 的独立模块边界，避免后处理逻辑再次混回 `resolution.py`。

## 测什么

- `validation_rules.table_rows` 会从标准化表格 block 中筛选命中行，排除 rejected 行，并记录 `validation_rule` action。
- `validation_rules.table_rows` 命中行但目标列为空时，不会用空字符串覆盖模型原始定案。
- 字段基础约束会把不在 `enum_values` 内或类型形状不匹配的 resolved 值降级为 failed，并记录 `field_constraint` action。

## 每个函数在干什么

`test_apply_validation_rules_corrects_table_rows_in_dedicated_module`

- 构造带 `validation_rules.source_type=table_rows` 的字段。
- 构造一段包含 selected / rejected 行的表格 block。
- 确认 `apply_validation_rules(...)` 只保留 selected 行，并输出 `validation_rule` action。

`test_apply_validation_rules_keeps_model_decision_when_target_column_is_empty`

- 构造一段命中 filter 但 `target_column` 为空的表格行。
- 确认 validation 不会把模型原始有效值覆盖成空 resolved。
- 确认没有追加误导性的 `validation_rule` action。

`test_apply_field_constraints_downgrades_invalid_enum_in_dedicated_module`

- 构造 enum 字段和一个模型返回的非法 resolved 决策。
- 确认 `apply_field_constraints(...)` 会把该字段降级为 failed。
- 确认失败 trace action 标记为 `field_constraint`。

`test_apply_field_constraints_downgrades_string_value_for_list_field`

- 构造 `type=list` 的学术论文名称字段。
- fake 模型把多值字段误输出成分隔符字符串。
- 确认基础字段约束会把该字段降级为 failed，并在 trace action 中记录 `field_type=list`。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_validation.py -q
```
