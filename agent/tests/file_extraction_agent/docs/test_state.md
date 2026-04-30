# `test_state.py`

## 基本实现思路

`service.file_extraction_agent.impl.state` 负责承载图运行时的内部中间态和可回查索引。

```text
build_graph_state(extraction_input)
  -> 接住已经由 input_adapter + block_contract 校验过的 ExtractionInput
  -> 按 block_id 建立 blocks_by_id
  -> 将 text / heading / text_line 等 block 切成 paragraph_index
  -> 将标准 Markdown table 或扁平 Markdown table 切成 table_row_index
  -> 初始化 candidates / broad_finishes / field_decisions / actions / warnings
  -> 运行过程中由 broad / resolution 节点写入候选、动作和最终定案
```

## 测什么

- `build_graph_state(...)` 会基于已有 `ExtractionInput` 生成索引和空状态。
- 真实 PDF 常见的单行扁平 Markdown 表格会保留空单元格并切成正确行。
- `impl/` 默认输入已经通过外层契约校验，不再重复承担 block_id 入口校验。
- `GraphState` 会保留已经准备好的候选、动作、字段定案和 warnings。

## 每个函数在干什么

`test_build_graph_state_initializes_indexes_and_empty_execution_state`

- 构造一份最小合法的 `ExtractionInput`。
- 确认状态对象会建立 `blocks_by_id`、`paragraph_index` 和 `table_row_index`。
- 确认候选池、broad 退出记录、字段定案和动作记录初始化为空。

`test_build_graph_state_splits_flattened_markdown_table_rows_with_empty_cells`

- 构造和真实 PDF 归一化结果一致的单行扁平 Markdown 表格。
- 表格同时包含“文明寝室”、空标记列和“模范寝室”。
- 确认行级索引能保留空单元格，并按表头输出 `列名=值` 文本。

`test_build_graph_state_assumes_input_adapter_already_validated_blocks`

- 绕过 input adapter 构造缺少 `block_id` 的输入。
- 确认 state 不再重复做入口契约校验，只是不为无 id block 建索引。

`test_graph_state_accepts_prepared_progress_payloads`

- 手工构造一份已有执行进度的 `GraphState`。
- 确认它能承载候选池、字段定案、动作记录和 warnings。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_state.py -q
```
