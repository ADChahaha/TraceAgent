# test_resolution_new.py

这份测试覆盖新 resolution prompt 和工具暴露顺序。模型应围绕虚拟文件树浏览材料，用 `reason` 解释用户可见动作，只要看到自己认为可能是字段证据的文本、列表项或表格行，就用 `bind_evidence` 立刻绑定 selector，不等字段值最终确定；如果某字段已有候选证据，写字段前必须用 `review_field` 复看这些候选证据；没有候选证据的字段不需要空 review。`write_field` 通过 `final_evidence` 提交复看后保留的最终证据，而且只能保留真正有用的 selector，丢弃只是同主题、背景、重复或弱相关的候选证据。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages
  -> build_tools
  -> 校验 prompt 不再包含 soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_virtual_tree_tools_without_plan`：确认 prompt 描述 `tree/read/anchors/query_table/bind_evidence/review_field/write_field/submit_result`，强调 `reason` 和 selector 证据，要求模型看到自己认为可能是字段证据的材料时立刻绑定 evidence，并要求有候选证据的字段先 `review_field` 再用 `write_field(... final_evidence ...)` 提交真正有用的证据；同时确认不再出现旧 plan、旧 block 工具和迁移期的旧概念禁止语。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段的 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态，避免模型只看到 `type=enum` 却不知道该写什么 JSON。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集已经收口到新的八个工具。
