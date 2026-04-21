# `test_input_adapter.py`

## 基本实现思路

`file_extraction_agent.input_adapter` 是 `file_extraction_agent` 进入抽取流程前的外部输入适配层。它不做 broad extraction，也不负责任何字段定案；它只把 backend 聚合后的 session 级输入收敛成稳定的 `GraphInput`，让后续 `processor` 和 graph 只消费内部统一契约。

这一层按下面的 pipeline 理解：

```text
调用方传入 session_id、documents，可选 task_spec 或 task_spec_name
  -> input_adapter.build_graph_input(...)
  -> 先确认 task_spec 与 task_spec_name 至少有一个可用
  -> 如果传了 task_spec 就直接使用
  -> 如果只传 task_spec_name 就从 task_specs/*.json 加载并校验成 TaskSpec
  -> 再把 session_id、documents、task_spec、run_config、metadata 组装成 GraphInput
  -> 返回给 processor 继续执行 broad extraction / resolution
```

## 测什么

- `input_adapter` 能把显式传入的 `task_spec` 收敛成 `GraphInput`
- `input_adapter` 支持按 `task_spec_name` 从 `task_specs/*.json` 加载 schema
- 适配结果会保留 `run_config` 和 `metadata` 这类 session 级上下文

## 每个函数在干什么

`test_build_graph_input_uses_explicit_task_spec`

- 直接构造一份合法的 `session_id + documents + task_spec`。
- 再补一份自定义 `run_config` 和 `metadata`。
- 确认 `build_graph_input(...)` 会优先使用显式传入的 `task_spec`，并把 session 级上下文完整带进 `GraphInput`。

`test_build_graph_input_loads_task_spec_from_name`

- 在临时目录里写一份最小 `task_specs/invoice.json`。
- 只传 `task_spec_name`，不直接传 `task_spec`。
- 确认 `input_adapter` 会从本地 task spec 文件加载 schema，并把它收敛进 `GraphInput`。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_input_adapter.py -q
```
