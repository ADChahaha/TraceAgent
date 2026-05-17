# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责四类高层规则：agent 身份和最终 `submit_result` 目标、assistant content 的用户可见阶段性说明语义、单轮单工具调用边界、`evidence://` locator/source citation 边界；`read`、`bind_evidence`、`review_evidences`、`write_field` 和 `submit_result` 的具体参数与证据规则放在各 tool description 中。运行时会向 provider 请求 `parallel_tool_calls=False`，如果模型仍同轮返回多个 tool call，则只保留并执行第一个。`read` 不再强制下一步必须是 `bind_evidence`，也没有无关记录工具；它一次只读取一个 paragraph/list/table block，公开 schema 只暴露 `path_id`，不暴露 `count/offset/limit` 这类连续读取或分页参数。`bind_evidence` 是宽松的候选笔记，只要某个显式 `evidence://` block link 可能相关就可以随时绑定，但一次只绑定一个字段和一个 paragraph/list/table block，避免模型读完整篇后做跨字段批量整理；`review_evidences` 再把 block 展开成 `evidence://.../Sxxx`、`evidence://.../Ixxx`、`evidence://.../Rxxx` inline link，并让模型判断当前候选是否足够写入或还需要继续找证据；只有 review 后觉得证据足够支撑字段决定，或足够判断 missing/null，才调用 `write_field`。assistant content 是可选的：机械导航、连续相邻 read、常规 bind 或普通 review 可以留空；完成语义阅读块、候选证据小组、review/write 切换、字段定案或失败修正时再输出短说明。只要 content 使用文档原文或原文语义，就必须写成 Markdown evidence link；有 inline selector 时优先用 `["quote"](evidence://0000.0001/S002)`，没有 inline selector 或必要时也可以用 block-level link，如 `["quote"](evidence://0000.0001.0014)`。`write_field` 的可见引用不要求 link target 与 `final_evidence` 完全同级，必要时可以只链到对应 paragraph/list/table block；`final_evidence` 参数本身必须复制 review snapshot 的 inline evidence links。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> 校验初始上下文包含 root depth=3 导航树
  -> 校验 read/bind/review/write 的局部约束主要存在于 tool description，而不是系统 prompt
  -> 校验 read 后可以自由继续浏览，并确认公开 read 只暴露 path_id 参数
  -> 校验 bind 通过显式 evidence:// block link 随时保存单字段、单 block 候选笔记
  -> 校验 review 用来判断候选是否足够写，普通 review 可静默，阶段变化时 assistant content 可以说明缺什么
  -> 校验 write 只能在 review 后判断证据足够时发生，并且 final_evidence 复制同字段当前 review snapshot 的 inline evidence links
  -> 校验模型绑定工具时请求 provider 关闭 parallel tool calls
  -> 校验每轮模型返回会先截断到第一个 tool call，再记录 model_message trace event，并把可选 content 作为兼容 reason 写入工具 action/event
  -> 校验真实模型调用默认使用 Responses API stream，并在失败时依次降级到 chat/completions stream 和非流调用
  -> 校验 Responses API content blocks 会被抽取成普通 model_message.content
  -> build_tools
  -> 校验具体工具规则进入 tool description，且工具 schema 不再暴露 reason 参数
  -> 校验 prompt 不再包含旧 anchors/query_table/review_field、soft plan / overview / record_note
```

## 测试函数

- `test_resolution_messages_describe_free_bind_policy_without_tool_manual`：确认系统 prompt 只保留身份目标、像人类阅读的可选阶段性 content 旁白、单轮单工具节奏、`evidence://` locator/source citation 边界；同时确认 `read` 的单 block 阅读规则、`bind_evidence` 的候选笔记语义、`review_evidences` 的 inline 展开规则、`write_field` 的 final evidence 规则和 `submit_result` 的 evidence 校验不再重复写进系统 prompt，而是由 tool description 承载；也确认不再提旧 `anchors/query_table/review_field` 主流程、旧 plan 工具、旧并发工具调用提示，以及旧的每轮/每次 read 必说话要求。
- `test_resolution_messages_include_depth_3_initial_tree_with_readable_files`：确认初始 resolution 上下文直接包含 root depth=3 的虚拟树，让模型无需先调用 `tree` 也能看到文档目录、一级 section 和一级 section 下的可读 `.md` 文件。
- `test_tool_descriptions_carry_free_bind_and_review_contracts`：确认各工具说明承载局部规则：`read` 不再要求立刻 bind，且一次只读一个显式 `evidence://` file block，公开 schema 只暴露 `path_id`，不再暴露 `count/offset/limit` 连续读取或分页参数；`read/bind/review` 的 assistant content 改为可选阶段性信号，机械相邻 read、常规 bind 和普通 review 不需要说话；`bind_evidence` 只接受一个显式 `evidence://` block link 和一个字段、不接受 inline links 或 `path_ids/bindings` 批量参数，且允许可能相关的宽绑定；`review_evidences` 负责展开 inline evidence links、要求只有证据足够才 write，并允许阶段变化时在 assistant content 说明缺什么；`write_field` 不要求紧跟 review，但只接受同字段当前 review snapshot 返回的 inline evidence links；同时确认 content citation 可以使用 inline evidence link，也允许必要时使用 paragraph/list/table block-level evidence link，且不要求 content link target 与 `final_evidence` 完全匹配；工具参数和 `final_evidence` 使用 `evidence://` links；所有工具 schema 都不再暴露 `reason` 参数。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集是新的六个工具。
- `test_resolution_graph_executes_only_first_model_tool_call_per_turn`：确认运行时向模型绑定工具时传入 `parallel_tool_calls=False`；如果模型仍然同轮返回多个 tool call，trace 和工具执行都只保留第一个，避免并发工具调用绕过前一个工具结果。
- `test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 resolution 调真实模型时优先使用 `stream(...)`，并能把 Responses API 的 text chunk、function call chunk 和 function call arguments chunk 合并成一个带 content 和 tool_calls 的 `AIMessage`。
- `test_resolution_falls_back_from_responses_stream_to_chat_stream_then_invoke`：确认 Responses stream 失败后会先尝试 chat/completions stream；两个 stream 都失败时，再降级到非流 invoke，并且成功后不继续调用后续 fallback。
- `test_resolution_records_text_from_responses_api_content_blocks`：确认 Responses API 返回的 content block 列表会抽取其中 `type=text` 的文本，写入 `model_message.content` 和工具 action/event 兼容 `reason`。
- `test_resolution_records_model_message_content_and_tool_calls_without_reasoning`：确认 resolution trace 会为每轮模型回复记录 `model_message` 事件，保存普通 `content`、tool call 数量和 tool call 参数摘要，便于检查模型是否同轮输出文本和调用工具；同时确认不会把 DeepSeek 的 `reasoning_content` 写入 trace。
- `test_tool_action_reason_comes_from_model_message_content`：确认工具 action/event 的兼容 `reason` 字段来自最近一轮 `model_message.content`，不是工具参数。
- `test_tool_action_reason_allows_empty_stage_content`：确认模型选择静默执行机械工具调用时，空 assistant content 会作为空字符串兼容写入 action/event 的 `reason`，不会被工具层当作错误。
