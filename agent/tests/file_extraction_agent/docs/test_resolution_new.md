# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责角色、单工具调用节奏、`reason` 语义、`path_id` locator 和 read judgement / evidence review lifecycle；具体参数约束写在各 tool description 中。模型每个 assistant turn 只能发一个 tool call，必须等待工具结果后再决定下一步；运行时也只执行第一个 tool call 作为兜底。每次成功 `read` 后，下一步必须是 `bind_evidence` 或 `skip_read`；`bind_evidence` 是宽松的候选笔记，只要当前 read 可能相关就可以先绑定；`review_evidences` 再把 block 展开成 Sxxx/Ixxx/Rxxx inline selector，并让模型判断当前候选是否足够写入或还需要继续找证据；`write_field(final_evidence=...)` 只能复制 review 返回的 inline selector，并且每次 `write_field` 前必须紧跟同字段 `review_evidences`。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> 校验初始上下文包含 root depth=3 导航树
  -> 校验 read 后必须判断，可能相关就先 bind 作为候选笔记
  -> 校验 review 用来判断候选是否足够写，继续读时 reason 要说明 review 发现缺什么
  -> 校验 write 前必须紧邻同字段 review，并且 prompt 要求复制 tree 返回的 path_id
  -> build_tools
  -> 校验具体工具规则进入 tool description
  -> 校验 prompt 不再包含旧 anchors/query_table/review_field、soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_read_judgement_policy_without_tool_manual`：确认系统 prompt 说明每次 read 后必须 `bind_evidence` 或 `skip_read`，bind 是宽松候选笔记而不是最终判断；review 展开 inline 并用于判断候选是否足够写，若继续读则下一步 reason 要说明 review 发现缺什么；每次 write 必须紧跟同字段 review 并复制 review 返回证据，同时要求使用 tree 显示的 `path_id`；同时确认不再提旧 `anchors/query_table/review_field` 主流程和旧 plan 工具。
- `test_resolution_messages_include_depth_3_initial_tree_with_readable_files`：确认初始 resolution 上下文直接包含 root depth=3 的虚拟树，让模型无需先调用 `tree` 也能看到文档目录、一级 section 和一级 section 下的可读 `.md` 文件。
- `test_tool_descriptions_carry_read_judgement_and_review_contracts`：确认各工具说明承载局部规则：`read` 成功后的下一步限制、`bind_evidence` 不接受 `path_id`/inline 参数且允许可能相关的宽绑定、`skip_read` 只用于无关 read、`review_evidences` 负责展开 inline 并要求继续读时说明缺什么、`write_field` 必须紧跟同字段 review 且只接受 review 返回的 final evidence。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集是新的七个工具。
- `test_resolution_limits_model_to_one_tool_call_per_turn`：确认运行时会把模型同轮返回的多个 tool call 收口为第一个。
