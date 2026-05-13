# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责角色、抽取流程、`reason` 语义和 evidence lifecycle；`tree/read/anchors/query_table/bind_evidence/review_field/write_field/submit_result` 的具体参数约束写在各自 tool description 里，由 LangGraph `bind_tools` 暴露给模型。模型应围绕虚拟文件树浏览材料，只要看到自己认为可能是字段证据的文本、列表项或表格行，就用 `bind_evidence` 立刻绑定 selector，不等字段值最终确定；如果某字段已有候选证据，写字段前必须用 `review_field` 复看这些候选证据；没有候选证据的字段不需要空 review。`write_field` 通过 `final_evidence` 提交复看后保留的最终证据，而且只能保留真正有用的 selector；只有 `null` 类型字段或 `null` enum variant 可以空 `final_evidence` 提交。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> build_tools
  -> 校验具体工具规则进入 tool description
  -> 校验 prompt 不再包含工具手册、soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_extraction_policy_without_tool_manual`：确认系统 prompt 只描述抽取策略、`reason`、候选 evidence、review/write/submit 流程和非 `null` 结果证据要求，不再把工具签名、read 目录规则或旧 plan、旧 block 工具说明塞进系统 prompt。
- `test_tool_descriptions_carry_navigation_and_evidence_contracts`：确认具体工具规则写在 tool description 中，尤其是 `read` 只能读 `.md/.list/.table`，目录路径必须先用 `tree` 展开，证据 selector、review、write 和 submit 校验规则也由对应工具说明承载。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段的 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态，避免模型只看到 `type=enum` 却不知道该写什么 JSON。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集已经收口到新的八个工具。
