# test_resolution_new.py

这份测试覆盖新 resolution prompt、工具说明和工具暴露顺序。系统 prompt 只负责全局规则：agent 身份和最终 `submit_result` 目标、assistant content 是给 reviewer 的进度更新而不是工具日志、单轮单工具调用边界、`evidence://` locator/source citation 边界。是否输出 assistant content 按“最新观察是否改变用户理解”动态判断，而不是按每个工具固定说话。

当前候选证据动作叫 `add_candidate_evidence`，强调它只是宽松的候选笔记：只要某个显式 `evidence://` block link 可能相关，就可以随时保存；一次只记录一个字段和一个 paragraph/list/table block。`review_evidences` 再把 block 展开成 inline link，让模型判断当前候选是否足够写入或还需要继续找证据。模型第一轮工具调用前必须先用 `task_spec` 语言写一句简短开场，说明要抽取哪些字段；之后才按动态内容规则决定是否说话。普通 `tree` 导航、调用 `read` 前、常规候选保存、重复相邻读取和纯 bookkeeping 都可以留空；`read` 返回后如果读到有意义内容，下一轮必须用 `task_spec` 语言自然一句话概括“看了什么、是否有价值”，不能因为原文语言而切换输出语言。任何陈述文档事实、证据状态或字段定案的可见句子都必须包含 Markdown evidence link，链接 label 优先翻译或改写成 `task_spec` 语言；只有正式名称、抽取值或不可翻译术语在翻译后会改变字段值时才保留原文。如果读到的内容很快会进入字段定案，read 概括只负责给 reviewer 定位，不提前完整写最终结论。模型应尽量按紧凑字段决策簇推进：`read` 相关 block 后，保存候选、复核证据并写入当前字段或语义块，再切到无关阅读；当 review 已经足够时，下一轮通常直接写同一字段。`review_evidences` 在下一步显然是 `write_field` 且事实已在 read 后概括过时可以静默，`write_field` 只做增量定案说明，避免把同一组原文事实完整重复两遍。如果 read 概括依赖同一 section 里的连续 block，优先用一个 `evidence://range/<start>/<end>` 覆盖整段连续 block，而不是只链第一个 block。需要更细粒度引用时，paragraph 句级用 `evidence://<block>/Sxxx`，list item 用 `evidence://<block>/Ixxx`，table row 用 `evidence://<block>/Rxxx`。可见文字不使用 `Read / Finding / Next` 等固定小标题，也不直接叙述工具名。

实现链路：

```text
documents + task_spec
  -> build_graph_state
  -> build_resolution_messages 生成系统级抽取策略
  -> 校验初始上下文只包含 task fields 和 tree-first 指令，不内联 root depth=3 导航树正文
  -> 校验 system prompt 只保留全局规则，并要求 assistant content 按最新观察的信息增量动态输出，同时使用 task_spec 主语言
  -> 校验可见 content 的文档事实、证据状态和字段定案必须带 Markdown evidence link，且链接 label 使用 task_spec 语言
  -> 校验模型按紧凑字段决策簇推进：read 定位、候选保存、review 和 write 尽量连续完成当前字段或语义块
  -> 校验 read 已经概括过的原文事实不会在后续 write_field 中完整重复，write 只补字段定案
  -> 校验 read/candidate/review/write 的局部约束放在 tool description，且不再使用固定可见说明模板
  -> 校验 read 后可以自由继续浏览，并确认公开 read 只暴露 path_id 参数
  -> 校验 add_candidate_evidence 通过显式 evidence:// block link 随时保存单字段、单 block 候选笔记，且常规保存不要求输出 assistant content
  -> 校验 review 用来判断候选是否足够写；证据足够时下一轮通常写同字段，下一步显然是 write 时 review content 可静默
  -> 校验 write 只能在 review 后判断证据足够时发生，字段写入作为判断点使用自然短句增量说明
  -> 校验模型工具绑定时请求 provider 关闭 parallel tool calls
  -> 校验每轮模型返回会先截断到第一个 tool call，再记录 model_message trace event
  -> 校验真实模型调用默认使用 Responses API stream，并在失败时依次降级到 chat/completions stream 和非流调用
  -> build_tools
  -> 校验具体工具规则进入 tool description，且工具 schema 不再暴露 reason 参数
  -> 校验工具 action/event 不再保存兼容 reason；用户可见文字只保留在 model_message.content
```

## 测试函数

- `test_resolution_messages_describe_candidate_policy_without_tool_manual`：确认 system prompt 只保留高层规则；第一轮工具调用前必须先用 `task_spec` 语言写一句简短开场；assistant content 后续按最新观察决定是否输出，不是逐工具日志；机械动作和普通候选保存可以留空，read 有价值时用 `task_spec` 主语言自然短句概括，同时确认 block range 和 Sxxx/Ixxx/Rxxx 细粒度 evidence link 格式都写入 prompt。
- `test_resolution_prompt_requires_task_spec_language_and_linked_evidence_content`：确认 system prompt 和 `read/review_evidences/write_field` 工具说明都要求可见 content 全程使用 `task_spec` 语言；文档事实、证据状态和字段定案必须带 Markdown evidence link；连续 block 的 read 概括优先使用 `evidence://range/<start>/<end>`；链接 label 使用 `task_spec` 语言释义而不是原文 quote。
- `test_resolution_messages_do_not_inline_initial_tree`：确认初始 resolution 上下文不再内联 root depth=3 虚拟树正文，只保留 task fields 和提示模型先调用 `tree` 导航的简短指令。
- `test_resolution_prompt_keeps_read_review_write_as_compact_decision_cluster`：确认 prompt 和工具描述要求模型按字段或语义块形成紧凑决策簇；read 概括只做定位，review 足够后下一轮通常直接写同字段，且 write 不完整重复 read 已经说过的同一组原文事实。
- `test_tool_descriptions_carry_candidate_and_review_contracts`：确认 `tree` 说明根目录使用空 path_id、文档目录示例为 `evidence://0001`；`read` 一次只读一个 block，并要求在读后有信息增量时自然概括；如果概括依赖同一 section 的连续 block，则用一个 `evidence://range/<start>/<end>` 覆盖整段连续 block；`add_candidate_evidence` 只接受一个字段和一个 block link，常规候选保存可以静默；`review_evidences` 展开 inline evidence links，并只在充分性变化或准备写入时输出；`write_field` 只能复制同字段当前 review snapshot 返回的 inline evidence links，并把字段写入作为自然短句判断点。
- `test_resolution_messages_expand_enum_variants`：确认 prompt 会把 enum 字段 variants 展开给模型，并说明 `write_field` 的 tagged enum value 形态。
- `test_resolution_graph_exposes_new_tools_only`：确认模型可见工具集是 `tree/read/add_candidate_evidence/review_evidences/write_field/submit_result`。
- `test_resolution_graph_executes_only_first_model_tool_call_per_turn`：确认运行时向模型绑定工具时传入 `parallel_tool_calls=False`；如果模型仍然同轮返回多个 tool call，trace 和工具执行都只保留第一个。
- `test_resolution_uses_responses_api_stream_and_merges_content_with_tool_calls`：确认 stream 调用能把 text chunk、function call chunk 和 arguments chunk 合并成带 content 和 tool_calls 的 `AIMessage`。
- `test_resolution_falls_back_from_responses_stream_to_chat_stream_then_invoke`：确认 Responses stream 失败后按顺序降级到 chat/completions stream 和非流 invoke。
- `test_resolution_records_text_from_responses_api_content_blocks`：确认 Responses API content block 列表会抽取 `type=text` 文本并写入 `model_message.content`。
- `test_resolution_records_model_message_content_and_tool_calls_without_reasoning`：确认 trace 保存普通 content 和 tool call 摘要，不保存 DeepSeek `reasoning_content`。
- `test_tool_actions_do_not_store_model_message_content_as_reason`：确认工具 action/event 不再把最近一轮 `model_message.content` 派生成 `reason`，工具记录只保留工具名、参数和结果。
- `test_tool_actions_do_not_write_empty_reason`：确认空 assistant content 不会让工具 action/event 写入空 `reason` 字段，也不会被工具层当作错误。
