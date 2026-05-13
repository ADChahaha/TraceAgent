# test_resolution_new.py

这份测试覆盖新 resolution prompt 和工具暴露顺序。模型应围绕虚拟文件树浏览材料，用 `reason` 解释用户可见动作，用 evidence selector 写字段，在拿到某个字段的足够证据后及时写入该字段，并调用 `submit_result` 完成。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages
  -> build_tools
  -> 校验 prompt 不再包含 soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_virtual_tree_tools_without_plan`：确认 prompt 描述 `tree/read/anchors/query_table/write_field/submit_result`，强调 `reason` 和 selector 证据，要求模型在有足够证据后写入字段，但不加入固定读写次数之类的工具节奏硬约束；同时确认不再出现旧 plan、旧 block 工具和迁移期的旧概念禁止语。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集已经收口到新的六个工具。
