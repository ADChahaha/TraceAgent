# `test_input_adapter.py`

## 基本实现思路

`file_extraction_agent.input_adapter` 负责把外部 blocks 主输入收敛成内部 `ExtractionInput`。

```text
调用方传入 blocks，可选再传 markdown / md_list，并必须显式传 task_spec
  -> input_adapter.build_graph_input(...)
  -> 校验 task_spec 存在
  -> 校验每个 block 都带有上游生成的 block_id
  -> 校验 block_id 在本次输入内唯一
  -> 组装内部 ExtractionInput
  -> 返回给 processor 继续执行 graph
```

## 测什么

- 显式 `task_spec` 会被优先收进 `ExtractionInput`
- 缺少显式 `task_spec` 时会被拒绝
- 缺少 `block_id` 的 blocks 会被拒绝，不再由 agent 兜底生成
- 重复 `block_id` 的 blocks 会被拒绝，避免 evidence 回查互相覆盖
- 合法的上游 `block_id` 会原样保留
- `run_options`、`metadata` 和备用文本上下文不会在适配时丢失

## 每个函数在干什么

`test_build_graph_input_uses_explicit_task_spec`

- 直接传一份 `blocks + task_spec`。
- 同时补 `markdown`、`run_options` 和 `metadata`。
- 确认 `build_graph_input(...)` 返回的是内部 `ExtractionInput`，而且关键字段完整保留。

`test_build_graph_input_requires_explicit_task_spec`

- 只传 blocks，不传 `task_spec`。
- 确认适配层拒绝进入内部抽取图。

`test_build_graph_input_requires_block_ids_from_upstream`

- 传入缺少 `block_id` 的 block。
- 确认适配层直接报错，不再生成任何兜底 id。

`test_build_graph_input_rejects_duplicate_block_ids`

- 传入两条共用同一个 `block_id` 的 blocks。
- 确认适配层拒绝进入内部抽取图。

`test_build_graph_input_preserves_valid_upstream_block_ids`

- 传入两条已经带有唯一 `block_id` 的 blocks。
- 确认 agent 不改写上游 id。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_input_adapter.py -q
```
