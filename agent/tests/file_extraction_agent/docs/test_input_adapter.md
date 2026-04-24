# `test_input_adapter.py`

## 基本实现思路

`file_extraction_agent.input_adapter` 负责把外部 blocks 主输入收敛成内部 `ExtractionInput`。

```text
调用方传入 blocks，可选再传 markdown / md_list，以及 task_spec 或 task_spec_name
  -> input_adapter.build_graph_input(...)
  -> 解析 task spec
  -> 组装内部 ExtractionInput
  -> 返回给 processor 继续执行 graph
```

## 测什么

- 显式 `task_spec` 会被优先收进 `ExtractionInput`
- `task_spec_name` 可以从 `task_specs/*.json` 加载并转成 `ExtractionInput`
- `run_options`、`metadata` 和备用文本上下文不会在适配时丢失

## 每个函数在干什么

`test_build_graph_input_uses_explicit_task_spec`

- 直接传一份 `blocks + task_spec`。
- 同时补 `markdown`、`run_options` 和 `metadata`。
- 确认 `build_graph_input(...)` 返回的是内部 `ExtractionInput`，而且关键字段完整保留。

`test_build_graph_input_loads_task_spec_from_name`

- 在临时目录写一份最小 task spec JSON。
- 只传 `task_spec_name`。
- 确认适配层会正确加载并组装内部输入对象。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_input_adapter.py -q
```
