# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责角色、抽取流程、`reason` 语义和 evidence lifecycle；`tree/read/anchors/query_table/bind_evidence/review_field/write_field/submit_result` 的具体参数约束写在各自 tool description 里，由 LangGraph `bind_tools` 暴露给模型，`task_spec` 不负责说明绑定工具顺序。模型每个 assistant turn 只能发一个 tool call，不能同轮返回多个或并行 tool calls，且必须等待工具结果后再决定下一步；运行时也只执行第一个 tool call 作为兜底。每个 `reason` 必须把上一轮 action 结果和本轮工具调用连起来：先说明上一轮看到了什么，再说明下一步准备调用什么工具；如果上一轮是 `read`，还要判断内容是否可能支持某个 schema 字段。模型看到可能支持字段的 paragraph 时，应先获取 inline 句子编号再绑定；看到可能支持字段的 list item 或 table row 时，应使用刚暴露的 Ixxx/Rxxx 立即绑定。候选绑定是 provisional collection，不是最终分类；模型应先绑定当前证据，再继续检查 supporting、qualifying 或 contrary clauses。同一 inline 来源可以连续绑定给多个字段；如果某字段已有候选证据，写字段前必须用 `review_field` 复看这些候选证据；没有候选证据的字段不需要空 review。`write_field` 通过 `final_evidence` 提交复看后保留的最终证据，而且只能保留真正有用的 selector；只有 `null` 类型字段或 `null` enum variant 可以空 `final_evidence` 提交。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> 校验 reason 必须分析上一轮 action 并说明下一轮 action
  -> build_tools
  -> 校验具体工具规则进入 tool description
  -> 校验 prompt 不再包含工具手册、soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_extraction_policy_without_tool_manual`：确认系统 prompt 只描述抽取策略、`reason`、候选 evidence、review/write/submit 流程和非 `null` 结果证据要求，并要求模型每轮只发一个 tool call、等待工具结果后再继续；同时要求 `reason` 先分析上一轮 action、再说明本轮工具；如果上一轮是 `read`，要判断是否支持字段并在需要时先取 inline id 再绑定，而且绑定是候选集合收集，检查其他条款要发生在绑定之后，不再把工具签名、read 目录规则或旧 plan、旧 block 工具说明塞进系统 prompt。
- `test_tool_descriptions_carry_navigation_and_evidence_contracts`：确认具体工具规则写在 tool description 中，尤其是 `read` 只能读 `.md/.list/.table`，目录路径必须先用 `tree` 展开，`anchors` 只能紧跟 paragraph `read`，`bind_evidence` 只能紧跟 inline-producing 结果，并允许同一 inline 来源连续多次 bind；证据 selector、review、write 和 submit 校验规则也由对应工具说明承载。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段的 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态，避免模型只看到 `type=enum` 却不知道该写什么 JSON。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集已经收口到新的八个工具。
