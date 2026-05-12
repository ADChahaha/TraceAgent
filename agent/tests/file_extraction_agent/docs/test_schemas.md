# test_schemas.py

这组测试覆盖 `service.file_extraction_agent.schemas` 的公开输入契约，确保 task spec、模型配置、运行预算和抽取结果的基础结构稳定。

实现链路：

```text
调用方传入 task_spec / model_config / run_options
  -> Pydantic 或 dataclass schema 解析
  -> 校验字段定义、模型参数和默认值
  -> 返回后续 graph 可消费的结构化对象
```

## 测试函数

- `test_task_spec_normalizes_field_dicts`：确认字段定义可以从 dict 或 `FieldDefinition` 构造，并且 `field_name` 会归一化到 `name`。
- `test_field_definition_rejects_untyped_list`：确认字段类型不再接受宽泛的 `list`，调用方必须声明 `list[string]` 或 `list[number]`。
- `test_field_definition_accepts_tagged_enum_variants_with_basic_payload_types`：确认 `enum` 字段可以声明多个 tagged variants，每个 variant 的 payload 类型只允许 `string`、`number`、`boolean`、`list[string]`、`list[number]` 或 `null`，并兼容 `bool` 写法归一化为 `boolean`。
- `test_field_definition_rejects_invalid_enum_shapes`：确认 `enum` 字段必须声明 variants、variant 名称不能重复、payload 类型不能是对象等复杂结构，非 enum 字段也不能携带 variants。
- `test_model_config_keeps_stage_model_names_and_sampling_options`：确认 resolution 模型名、采样参数、连接配置、重试次数和请求超时会原样保存。
- `test_run_options_defaults_to_tool_budget_only`：确认运行预算默认只暴露 `max_tool_calls`。
- `test_extraction_result_defaults_to_completed_empty_payload`：确认空 `ExtractionResult` 默认是 completed，并带空 result/trace。
