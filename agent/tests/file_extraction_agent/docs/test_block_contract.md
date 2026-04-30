# `test_block_contract.py`

## 基本实现思路

`service.file_extraction_agent.block_contract` 是进入抽取图前的 blocks 契约门禁。

```text
外部传入 blocks
  -> 确认是非空列表
  -> 逐项检查 document_id / block_id / kind / text
  -> 检查 block_id 在本次输入内唯一
  -> 对 table block 验证至少能切成行级文本
  -> 校验通过后返回 None，后续 input_adapter 再组装 ExtractionInput
```

## 测什么

- 合法 text/table block 可以通过契约校验。
- 空列表、缺少 trace 必需字段或重复 `block_id` 会被拒绝。
- table block 不能转换成行级文本时会在外层失败。

## 每个函数在干什么

`test_validate_blocks_contract_accepts_traceable_text_and_table_blocks`

- 构造一个 text block 和一个 markdown table block。
- 确认二者都具备后续 trace 和候选池所需的最小字段。

`test_validate_blocks_contract_rejects_empty_input_and_missing_trace_fields`

- 分别传入空 blocks、缺少 `document_id`、缺少 `block_id` 的输入。
- 确认错误在进入 `impl/` 前暴露。

`test_validate_blocks_contract_rejects_duplicate_block_ids`

- 构造两个同 id block。
- 确认外层契约拒绝重复来源定位。

`test_validate_blocks_contract_rejects_unreadable_table_blocks`

- 构造无法拆出 markdown table 行的 table block。
- 确认表格检索前置条件不满足时直接失败。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_block_contract.py -q
```
