# `test_processor.py`

## 基本实现思路

`file_extraction_agent.processor` 是这个模块的对外总入口。它不再自己承担外部输入适配，而是把抽取 pipeline 串起来：接住 session 级输入，转交给 `input_adapter.build_graph_input(...)` 组装 `GraphInput`，调用 extractor client 产出 broad extraction，再把字段结果收口成 `ExtractionResult`。

这层当前按下面的 pipeline 理解：

```text
调用方传入 session_id + documents，再传 task_spec 或 task_spec_name
  -> processor.extract(...)
  -> 先把 session 级输入转交给 input_adapter.build_graph_input(...)
  -> input_adapter 负责选择 task_spec，并组装 GraphInput
  -> 调用 extractor_client.invoke(..., output_schema=BroadExtractionOutput) 获取字段候选
  -> 按 task_spec.fields 的顺序对每个字段做最小定案：单一候选就 resolved，空候选就 failed，多候选冲突也 failed
  -> 返回 broad_output + resolved_fields + run_trace 组成的 ExtractionResult
```

## 测什么

- `processor` 会从 `session_id + documents + task_spec` 组装 pipeline 入口
- `processor` 会把 session 级输入委托给 `input_adapter`
- `processor` 支持通过 `task_spec_name` 从 `task_specs/*.json` 加载 schema
- broad extraction 没有候选值时，会在最终结果里收口成 `failed`
- broad extraction 缺少某个字段输出时，会按 `task_spec.fields` 顺序补一个失败结果，而不是丢字段
- 缺少 `task_spec` 和 `task_spec_name` 时会拒绝继续执行

## 每个函数在干什么

`test_extract_delegates_graph_input_building_to_input_adapter`

- 用假的 `build_graph_input(...)` 返回一份已经适配好的 `GraphInput`。
- 再让假的 extractor client 读取这份适配后的 session 内容。
- 确认 `processor.extract(...)` 会把原始 session 参数先交给 `input_adapter`，而不是自己绕过适配层组装图输入。

`test_extract_builds_graph_input_from_prevalidated_documents_and_task_spec`

- 直接构造一份合法的 `session_id + documents + task_spec`。
- 用假的 extractor client 返回一个单候选 broad extraction。
- 确认 `processor.extract(...)` 经过 `input_adapter` 收敛输入后，能把单候选 broad extraction 收口成 `resolved`。

`test_extract_loads_task_spec_from_task_spec_name`

- 在临时目录里写一份 `task_specs/invoice.json`。
- 只传 `task_spec_name`，不直接传 `task_spec`。
- 确认 `processor` 会先加载 task spec，再把空候选收口成 `failed`。

`test_extract_uses_task_spec_order_to_fill_missing_field_outputs`

- 构造一个有两个字段的 `TaskSpec`，但让 broad extraction 只返回其中一个字段。
- 确认 `processor` 会按 task spec 顺序补齐最终结果，让缺失字段显式变成 `failed`。

`test_extract_rejects_missing_task_spec_and_task_spec_name`

- 故意只传 `session_id` 和 documents，不传任何 task spec 信息。
- 确认入口会拒绝继续执行，避免编排层在 schema 未确定的情况下进入抽取流程。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
cd ./agent
python -m pytest tests/file_extraction_agent/test_processor.py -q
```
