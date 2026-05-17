# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责四类高层规则：agent 身份和最终 `submit_result` 目标、assistant content 的 Codex-style 用户可见进度说明、单轮单工具调用边界、`evidence://` locator/source citation 边界。`read`、`add_candidate_evidence`、`review_evidences`、`write_field` 和 `submit_result` 的具体参数与证据规则放在各 tool description 中。

当前候选证据动作叫 `add_candidate_evidence`，强调它只是宽松的候选笔记：只要某个显式 `evidence://` block link 可能相关，就可以随时保存；一次只记录一个字段和一个 paragraph/list/table block。`review_evidences` 再把 block 展开成 inline link，让模型判断当前候选是否足够写入或还需要继续找证据。assistant content 在首轮工具调用前必须先给人类 reviewer 一个短 preamble；开始新的阅读组前要说明准备看哪里和为什么看；机械导航和连续相邻 read 可以留空，但连续 `tree/read` 超过十步且有新发现时不能继续沉默。调用 `add_candidate_evidence` 前必须用一两句说明为什么这个 block 值得为该字段保存；如果引用原文，必须写成 `["原文短语"](evidence://...)` 这样的 Markdown evidence link，不能只用裸引号。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> 校验初始上下文只包含 task fields 和 tree-first 指令，不内联 root depth=3 导航树正文
  -> 校验 assistant content 是短的人类进度说明，不是工具调用日志
  -> 校验首轮工具调用前必须有短 preamble，开始新阅读组前要说明意图，长导航/read 过程不能一直静默
  -> 校验完成短局部阅读块、字段相关发现、review/write 转换或错误修正时，才需要说明具体发现和下一步
  -> 校验 read/candidate/review/write 的局部约束主要存在于 tool description，而不是 system prompt
  -> 校验 read 后可以自由继续浏览，并确认公开 read 只暴露 path_id 参数
  -> 校验 add_candidate_evidence 通过显式 evidence:// block link 随时保存单字段、单 block 候选笔记，并要求调用前说明保存理由
  -> 校验 review 用来判断候选是否足够写，普通 review 可静默，阶段变化时 assistant content 可以说明缺什么
  -> 校验 write 只能在 review 后判断证据足够时发生，并且 final_evidence 复制同字段当前 review snapshot 的 inline evidence links
  -> 校验模型工具绑定时请求 provider 关闭 parallel tool calls
  -> 校验每轮模型返回会先截断到第一个 tool call，再记录 model_message trace event
  -> 校验真实模型调用默认使用 Responses API stream，并在失败时依次降级到 chat/completions stream 和非流调用
  -> build_tools
  -> 校验具体工具规则进入 tool description，且工具 schema 不再暴露 reason 参数
```

## 测试函数

- `test_resolution_messages_describe_candidate_policy_without_tool_manual`：确认 system prompt 只保留高层规则；assistant content 是 Codex-style 的短进度说明，首轮工具调用前必须说明先看目录和可能相关条款，开始新阅读组前要说明意图，连续 `tree/read` 最多十步后如果有新发现要更新；短局部阅读块、字段相关发现、候选组 review/write 转换或错误修正时说明具体发现和下一步；同时确认引用原文必须使用 Markdown evidence link，旧 `bind_evidence` 词不会出现在候选工具说明里。
- `test_resolution_messages_do_not_inline_initial_tree`：确认初始 resolution 上下文不再内联 root depth=3 虚拟树正文，只保留 task fields 和提示模型先调用 `tree` 导航的简短指令。
- `test_tool_descriptions_carry_candidate_and_review_contracts`：确认 `read` 一次只读一个 block，`add_candidate_evidence` 只接受一个字段和一个 block link，且调用前要用 assistant content 说明为什么为该字段保存这个候选，并用 Markdown evidence link 指向正在保存的 block；`review_evidences` 展开 inline evidence links，`write_field` 只能复制同字段当前 review snapshot 返回的 inline evidence links。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集是 `tree/read/add_candidate_evidence/review_evidences/write_field/submit_result`。
- `test_resolution_graph_executes_only_first_model_tool_call_per_turn`：确认运行时向模型绑定工具时传入 `parallel_tool_calls=False`；如果模型仍然同轮返回多个 tool call，trace 和工具执行都只保留第一个。
- `test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 stream 调用能把 text chunk、function call chunk 和 arguments chunk 合并成带 content 和 tool_calls 的 `AIMessage`。
- `test_resolution_falls_back_from_responses_stream_to_chat_stream_then_invoke`：确认 Responses stream 失败后按顺序降级到 chat/completions stream 和非流 invoke。
- `test_resolution_records_text_from_responses_api_content_blocks`：确认 Responses API content block 列表会抽取 `type=text` 文本并写入 `model_message.content`。
- `test_resolution_records_model_message_content_and_tool_calls_without_reasoning`：确认 trace 保存普通 content 和 tool call 摘要，不保存 DeepSeek `reasoning_content`。
- `test_tool_action_reason_comes_from_model_message_content`：确认工具 action/event 的兼容 `reason` 字段来自最近一轮 `model_message.content`。
- `test_tool_action_reason_allows_empty_stage_content`：确认空 assistant content 会作为空字符串兼容写入 action/event 的 `reason`，不会被工具层当作错误。
