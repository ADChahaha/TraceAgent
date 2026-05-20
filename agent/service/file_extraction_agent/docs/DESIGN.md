# File Extraction Agent Design

本文记录 `file_extraction_agent` 当前的架构方向：把语义 HTML 暴露成只读虚拟文件树，让模型按用户给定 schema 从多文件文档中抽取字段，并用 paragraph 句子编号、list item 编号和 table row 编号做 inline 证据归因。

本文不设计模型自由书写的 plan 或面向用户的计划叙事。

## 核心思路

抽取链路分成三层：

```text
用户给定 schema + 多个语义 HTML 文件
  -> 构建只读 semantic HTML virtual tree
  -> resolution 初始上下文只写入 task fields 和“先用 tree 导航”的指令，不内联任何 tree 正文
  -> 模型先调用 tree 展开目录，再用 read 浏览文件、章节和段落；模型可见 locator 统一显示为 `evidence://...`
  -> 模型像人类读文档一样推进；assistant content 是按信息增量触发的用户可见进度更新，不是工具调用日志
  -> read 一次只打开一个 paragraph/list/table；需要继续看相邻内容时，模型必须再次调用 read
  -> read 调用前通常不说话；read 返回后如果内容有意义，下一轮用 task_spec 主语言自然概括看了什么、是否有价值
  -> read 概括只负责给 reviewer 定位当前发现；如果同一组事实很快会被写字段，最终字段结论留到 write_field
  -> 如果某个已知 block 可能支持、反驳、限定或帮助排除字段，模型用 add_candidate_evidence 保存候选 block evidence
  -> add_candidate_evidence 是内部候选笔记，常规保存可以静默；只有证据图景变化、候选组完成或相关性不明显时才输出进度更新
  -> 模型用 review_evidences 像看笔记一样复看某字段的候选 block evidence，并由工具展开成 `evidence://.../Sxxx`、`evidence://.../Ixxx`、`evidence://.../Rxxx` inline link
  -> 模型尽量按字段或语义块形成紧凑决策簇：读相关 block、保存候选、review、write 当前字段后，再切到无关阅读
  -> review_evidences 只有在证据不足、缺口明确或需要改变 reviewer 理解时输出进度更新；如果下一步显然是 write_field，可以静默
  -> 模型在 review 后判断证据足够支撑字段决定，下一轮通常直接复制当前 review snapshot 里的 inline evidence link 写入同一字段
  -> write_field 是字段定案点，通常用自然短句说明字段值或缺失状态为什么由 review 支持；如果 read 已经概括过同一组事实，write 只做增量定案说明，避免完整重复
  -> submit_result 内部按 schema 校验并返回最终结果或错误
```

`schema` 是用户给定的抽取契约，直接放在模型上下文里，不作为虚拟文件树的一部分，也不提供写 schema 工具。虚拟文件树只表达待抽取材料；字段结果通过专门的结果写入工具提交。

对外返回给 backend 的终态结果也属于契约的一部分：`result.fields[]` 和 `trace.fields[]` 都必须显式使用 `field_name`，不能把内部写入态里的 `field_id` 直接透出。

如果字段类型是 `enum`，resolution prompt 会把 variants 展开成 `VariantName(payload_type)`，并提示模型用 tagged enum object 写入：

```json
{"variant": "Entailment", "value": null}
```

## 语义 HTML 虚拟文件树

虚拟文件树不在磁盘上创建真实文件。它是基于 HTML AST / 语义节点索引生成的只读视图，专门给模型做导航。

建模规则：

- 根目录固定为 `/`。
- 每个输入 HTML 文件是根目录下的一个目录。
- 文档目录名使用编号、源文件名和文档 title 组合，避免多文件同名冲突。
- section header 是目录。
- paragraph 是 `.md` 文件。
- list 是 `.list` 文件。
- table 是 `.table` 文件。
- paragraph 文件名使用编号和段落前 `n` 个清洗后的可见字符。
- list 文件名使用编号和列表标题、首个 item 或短 preview。
- table 文件名使用编号和 caption、最近 section header 或表头列 preview。
- title 不单独作为可读文件；它进入文档目录名。
- `read` 按文件类型返回 paragraph/list/table 的 Markdown 阅读视图。

示例：

```text
/
└── evidence://0001 file1-项目设计说明/
    ├── evidence://0001.0000.0001 封面上未归入 section 的段落.md
    ├── evidence://0001.0001 背景/
    │   ├── evidence://0001.0001.0001 这个项目最初是为了.md
    │   └── evidence://0001.0001.0002 后来我们发现模型.md
    └── evidence://0001.0002 实现方案/
        ├── evidence://0001.0002.0001 系统会先解析HTML.md
        ├── evidence://0001.0002.0002 关键步骤.list
        ├── evidence://0001.0002.0003 费用明细.table
        └── evidence://0001.0002.0004 虚拟树不会落盘.md
```

编号是路径稳定性的基础：

- 文档目录的模型可见 path_id 使用 `0001`、`0002` 区分多个输入文件，根目录 `/` 不再暴露成 `evidence://0000`。
- 文档目录直下、尚未归入任何 section 的 paragraph/list/table 使用 `文档 path_id.0000.xxxx`，例如 `0001.0000.0001`。
- section 目录使用文档或上级 section 内的同级编号区分相同 header。
- paragraph、list 和 table 文件使用所在目录内的同级编号保留原文 block 顺序并避免 snippet 重复。

这些 `001-` / `002-` 同级编号只存在于内部 raw path。模型可见的 `tree` 行使用 `evidence://<path_id>` 承担去重和定位职责，所以显示名会去掉同级编号前缀，避免重复噪音。显示名还会 percent-decode，例如把 `Confidentiality%20Agreement` 显示为 `Confidentiality Agreement`；内部 raw path 保持原样，避免破坏已有索引兼容。

raw virtual path 是内部索引，不再作为模型可见 locator。`HtmlDocument` 会同时维护 `nodes_by_path` 和 `nodes_by_path_id`：raw path 用于内部调试和兼容底层查询，`path_id` 是内部稳定编号。模型看到和传入工具的 locator 是 `evidence://<path_id>`，例如第一个文档为 `evidence://0001`，文档直下第一个可读 block 为 `evidence://0001.0000.0001`，文档下第一个 section 为 `evidence://0001.0001`。旧的方括号格式 `[0001.0001]` 不是别名，工具参数会直接拒绝。

`HtmlDocument.source_selectors()` 只为 paragraph/list/table 可读叶子节点生成映射；section、document 和 root 目录不进入映射，避免前端把一个目录高亮成一大片原文。它会从虚拟节点对应的原始 HTML 节点上读取 `id`，如果没有 `id` 再看 `data-element-id`，生成内部 `path_id -> 原始 DOM id` 映射。backend 生成 replay 时会用这张表把展示 HTML 的节点 id 改写成虚拟 `path_id`，前端最终只需要用 path_id 定位。

`run_extraction_graph_stream` 在进入模型 resolution 前会先输出 `source_indexed` 事件，其中包含当前 `document_tree` 和 `source_selectors`。backend 可以在任务还在运行时先用这张映射改写 replay HTML，让前端点击 live read/add_candidate_evidence 工具行也能打开原文并高亮。最终 `validate_and_build_result` 仍会在 trace 里附带同样的内部 `source_selectors`，作为终态 replay 的权威映射。

模型只能复制 tree 输出里的 `evidence://` locator。工具返回给模型的候选 evidence、`review_evidences.evidence` 和 `write_field(final_evidence=...)` 都使用 evidence links；工具内部会把这些 link 转成 canonical `path_id` selector，最终结果和 scorer 仍使用 `path_id + Sxxx/Ixxx/Rxxx` 反查原文。

## 工具边界

面向模型的最小工具集合：

```text
tree(path_id="", depth=3)
read(path_id="evidence://...")
add_candidate_evidence(field_id, path_id="evidence://...")
review_evidences(field_id)
write_field(field_id, value, final_evidence, status?)  # final_evidence 必须复制同字段当前 review snapshot 的 inline evidence links
submit_result()
```

系统 prompt 只保留全局约束：agent 身份和最终 `submit_result` 目标、第一轮工具调用前先用 `task_spec` 主语言写一句简短开场、assistant content 是给 reviewer 的进度更新而不是工具调用日志、单轮单工具调用节奏、`task_spec` 主语言输出，以及 `evidence://` locator 和 source citation 边界。`read`、`add_candidate_evidence`、`review_evidences`、`write_field`、`submit_result` 的具体参数、证据规则和何时值得输出进度更新写在各 tool description 中，并通过 LangGraph `bind_tools` 暴露给模型。这样模型在选择某个工具时能直接看到该工具的局部规则，例如 `read` 只能读取 tree 输出中 `.md/.list/.table` 文件对应的 evidence link，目录 evidence link 必须先用 `tree` 展开。

工具参数不再包含 `reason`。assistant content 不是每轮工具调用都必须输出的理由，也不是工具调用日志。除第一轮工具调用前固定先说一句开场外，后续按“最新观察是否改变 reviewer 的理解”动态决定：

```text
tree 导航、read 调用前、常规候选保存、相邻重复读取、纯 bookkeeping
  -> assistant content 可以为空

read 返回后读到有价值内容、几个 read 形成完整语义块、预期区域被排除
  -> 下一轮用自然短句概括看了什么、是否支持字段或为什么继续找
  -> 如果这些事实很快会被写入字段，只做短定位，不提前完整写最终字段结论
  -> 如果这个概括依赖同一 section 里的连续 block，可以在 assistant content 里用一个 `evidence://range/<start>/<end>` 覆盖整段连续 block，而不是只链第一个 block

review_evidences 发现证据不足、缺口明确或改变下一步动作
  -> 用自然短句说明当前证据状态和字段是否可以定案
  -> 如果证据足够且下一步显然是 write_field，assistant content 可以为空

write_field 写入、修正或标记 missing
  -> 用自然短句说明字段结论，并链接 reviewed evidence 或说明 reviewed absence basis
  -> 如果 read 后已经说过同一组原文事实，不完整复述，只补字段定案或差异

submit_result 成功或返回校验错误
  -> 用自然短句说明提交结果或需要修正的点
```

可见进度更新必须使用 `task_spec` 语言；如果 `task_spec` 混合多种语言，优先跟随字段描述和 instructions 的主要语言，不能因为原文是日文、英文或其他语言就切换输出语言。证据链接的 label 也应翻译或改写成 `task_spec` 语言；只有专有名词、正式名称、抽取值或不可翻译术语在翻译后会改变字段值时，才保留原文。模型不使用固定小标题，也不直接叙述工具名。

只要 assistant content 的某句话陈述了文档事实、证据充分/缺失状态、候选相关性或字段定案，就必须包含 Markdown evidence link，不能输出没有链接的文档事实。还没有 Sxxx/Ixxx/Rxxx selector 时，用 paragraph/list/table block 链接，例如 `[保密义务条款](evidence://0001.0012.0001)`；如果 read 概括依赖同一 section 的连续 block，优先用一个 `evidence://range/<start>/<end>` 覆盖整段连续 block，而不是只链开头 block；需要句、项、行级引用时，paragraph 用 `evidence://<block>/Sxxx`，list 用 `evidence://<block>/Ixxx`，table 用 `evidence://<block>/Rxxx`；已经有 inline selector 时优先用 inline 链接，例如 `[仅限本协议相关用途](evidence://0001.0014.0001/S002)`。调用 `add_candidate_evidence` 前，如果引用正在保存的 block 内容，content 必须包含指向同一个 block path_id 的 Markdown evidence link。`write_field` 是字段定案动作；非空 `final_evidence` 的 write content 应包含 `task_spec` 语言的简短释义或必要抽取值，并链接到对应 inline selector 或它所在的 paragraph/list/table block。可信证据仍只来自虚拟路径和文件内编号，assistant content 不是模型隐藏推理链。

resolution system prompt 要求每轮只调用一个工具，避免模型批量扫、批量 review、批量写，保持接近人类阅读节奏。运行时也会在 `bind_tools` 时请求关闭 provider 侧 parallel tool calls；如果模型仍然同轮返回多个 tool call，运行时只保留并执行第一个，再把截断后的单个 tool call 写入 `model_message` trace。依赖前一个工具输出的动作必须等结果回来后再做，例如 `write_field` 不能和它所依赖的 `review_evidences` 放在同一轮。模型应把 `review_evidences` 当成复看候选证据的判断点：只有 review 后觉得证据足够支撑字段决定，或者足够判断 missing/null，才写字段；不够就继续读或继续添加候选证据。为了避免用户在长 trace 里看到同一内容两次，prompt 要求模型按紧凑字段决策簇推进：如果刚刚读到的一组 block 已经足够支持某字段，就优先完成该字段的候选保存、review 和 write，再切到无关字段；review 足够后下一轮通常写同字段，除非明确说明具体证据缺口。

assistant content 的推荐形态是短进度更新，而不是固定模板。普通机械导航、准备调用 `read`、常规候选保存和重复读取可以留空；`read` 返回后如果读到实质内容，下一轮再概括刚看的内容，但这个概括用于定位发现，不提前完整写最终字段结论；`review_evidences` 如果下一步显然是 `write_field` 且 facts 已经在 read 后说明过，可以静默；`write_field` 作为字段定案阶段，assistant content 通常应写清楚字段结论、选择该值的理由和引用标记，但不完整重复前面 read 已经说过的同一组事实。

### Trace 事件

resolution trace 同时记录模型回复和工具动作：

```text
build_graph_state(documents + task_spec)
  -> 先输出 source_indexed(document_tree + source_selectors)，供前端运行中打开原文和高亮
model.stream(messages)
  -> 真实模型优先使用 Responses API streaming 形态，保留同轮 assistant content 和 tool_call
  -> 如果 Responses stream 失败，降级到 chat/completions stream
  -> 如果两个 stream 形态都失败，降级到 Responses 非流调用，再降级到 chat/completions 非流调用
  -> 合并 text delta、function_call 和 function_call_arguments delta，归一成一个 AIMessage
  -> 记录 model_message：普通 content、tool_call_count、tool_calls 的 id/name/args
  -> 如果同轮有多个 tool call，运行时只保留第一个，避免并发工具调用影响模型反馈链
  -> ToolNode 执行工具
  -> 记录 tool_started / tool_completed 以及字段或结果事件
```

`model_message` 用来调试模型是否在同一轮既输出普通文本又发起 tool call。模型工厂构造一个按顺序尝试的 fallback chain：`responses_stream -> chat_completions_stream -> responses_invoke -> chat_completions_invoke`。resolution graph 优先使用 stream 语义；如果当前 stream attempt 抛错或没有返回任何 chunk，才尝试下一种 transport。运行时把 stream chunk 合并成一个普通 `AIMessage` 后再交给 trace 和 ToolNode，因此 trace 能保存用户可见 assistant content，工具执行仍使用完整 tool call 参数。普通 chat-completions tool-call stream 不是主路径，因为该路径在部分 provider 上只返回 function-call delta，不返回 assistant text；它只作为 Responses stream 失败后的备用。`model_message` 只保存模型返回的普通 `content` 和工具调用摘要，不保存 DeepSeek `reasoning_content` 这类隐藏思考内容。工具 action/event 不再保存 `reason` 字段；用户可见文字只来自 `model_message.content`，工具记录只表达工具名、参数和结果。

候选证据记录是 provisional collection，不是最终字段分类或定案。`add_candidate_evidence` 使用显式 `evidence://` block link 保存 block 级候选 evidence，不依赖上一轮是不是 `read`，也不接受 Sxxx/Ixxx/Rxxx inline selector。一次 `add_candidate_evidence` 只保存一个字段和一个 paragraph/list/table block；如果同一个对象可能支持多个字段，或者同一字段需要继续补充更多对象，模型需要分多次调用。模型看到某个 paragraph/list/table 可能支持、反驳或限定某个字段时，可以直接把该 block link 记入候选集合；不确定但可能相关的对象也应该先保存为候选笔记。常规候选保存可以静默；只有候选改变证据图景、完成一组关键候选，或者相关性不明显时，assistant content 才需要用自然短句说明。如果引用原文，必须用 Markdown evidence link 指向正在保存的同一个 block path_id，不能只写裸引号，也不能把本轮写成刚刚完成的新阅读。候选 evidence 可以比最终 evidence 更宽、更粗，也可能包含后续会被筛掉的对象；`final_evidence` 必须等 `review_evidences` 展开 inline selector 后再选择，通常是候选 block 里的更小或不同的 inline 子集。`task_spec` 只描述字段语义和输出类型，不负责说明工具调用顺序。

### `tree`

resolution 的初始 human message 不再直接包含 `tree(depth=3)` 等价的导航树。模型只能先看到字段定义和一条“先用 tree 导航”的简短指令，因此第一步如果需要定位文档内容，应主动调用 `tree`。这样首轮导航也会进入 trace，便于人类 reviewer 看到模型是如何打开目录的。

初始 prompt 输入链路是：

```text
documents + task_spec
  -> 构建 HtmlDocument 虚拟树索引
  -> build_resolution_messages 只写入 Task fields 和 tree-first 指令
  -> 模型调用 tree(path_id="", depth=3) 或按需选择更小 depth
  -> tree 返回目录和 paragraph/list/table 文件 evidence link
  -> 模型再 read 具体文件
```

如果模型调用 `tree(path_id="", depth=3)`，层级覆盖根目录、文档目录、一级 section，以及一级 section 下的 paragraph/list/table 文件：

```text
/
  -> 0001 文档目录/
  -> 0001.0000.0001 文档直下可读 paragraph/list/table 文件
  -> 0001.0001 一级 section/
  -> 0001.0001.0001 section 内可读 paragraph/list/table 文件
```

这样当 OCR 或语义解析把实质条款挂到标题看似无关的目录下时，模型可以通过显式 `tree` 调用看到该目录下的可读文件。`tree` 只提供导航，不返回 paragraph 正文，不作为最终 evidence。结果 trace 仍会保存 `document_tree=state.document.tree_text("/", depth=3)`，但这只是调试和前端展示记录，不代表这些 tree 行被注入给模型。

`tree` 返回虚拟文件树的目录和 paragraph 文件名，是模型继续展开更深目录的入口。

```text
tree(path_id="", depth=1)
  -> 返回所有文档目录

tree("0001", depth=2)
  -> 返回该文档下的 section 和 paragraph/list/table 文件
```

`tree` 不返回 paragraph 正文，不返回 schema，也不承担搜索职责。

### `read`

`read` 按虚拟文件类型返回 Markdown 阅读视图。公开工具只接收一个 `path_id` 参数。paragraph 默认返回完整正文，不带句子编号；list 和 table 默认返回完整对象并带 item/row 编号，便于模型判断这个对象是否可能支持字段。`read` 只负责阅读，不再建立“待读后判断”状态，也不限制下一步工具；模型可以继续 `tree/read/review_evidences/add_candidate_evidence/write_field/submit_result`，由 prompt 引导它在合适时机保存候选证据。

`read` 一次只读取一个明确的 paragraph/list/table block：

```text
read(evidence://...)
  -> 先校验 evidence link 指向 paragraph/list/table
  -> 只返回这个 block 的 Markdown 阅读视图
  -> 如果需要相邻 block，模型必须根据 tree 里的相邻 evidence link 再调用一次 read
```

这样 trace 不会把多个相邻对象打包进一次读取；人类 reviewer 能逐块看到模型读了什么、为什么读、以及后续是否保存为候选。

```text
read("evidence://0001.0002.0001")
  -> "系统会先解析 HTML，并按 heading 层级生成语义树。..."
```

阅读链路是：

```text
read(evidence://...)
  -> 返回一个 paragraph/list/table block
  -> 如果返回的某个 locator 可能支持字段，可现在或稍后用 add_candidate_evidence(field_id, path_id=evidence://...) 保存候选 block
  -> 也可以继续 tree/read/review_evidences/write_field/submit_result
```

`add_candidate_evidence` 不需要紧跟 `read`，只要求传入可读文件的 `evidence://` block link。如果刚读到的对象无关，模型直接继续浏览或 review/write，不需要额外工具记录无关判断。

list 返回 Markdown list，前置少量 metadata，并给每个 item 稳定编号：

```markdown
---
kind: list
path_id: 0001.0002.0002
title: 关键步骤
showing: 1-3
---

- [I001] 解析 HTML 并构建语义节点。
- [I002] 按 heading 生成 section 目录。
  - [I002.001] 子列表保留层级编号。
- [I003] 将 paragraph、list、table 暴露成虚拟文件。
```

table 返回 Markdown table，前置少量 metadata，并给每行稳定编号：

```markdown
---
kind: table
path_id: 0001.0002.0003
title: 费用明细
rows: 238
columns: 项目 | 金额 | 日期
showing: 1-238
---

| row | 项目 | 金额 | 日期 |
| --- | --- | --- | --- |
| R001 | 服务费 | 1000 | 2024-01-01 |
| R002 | 押金 | 500 | 2024-01-02 |
```

`offset` 和 `limit` 用于 list/table 显式分页；默认读取整个 list/table，便于模型在一次 read 后完整判断当前对象是否值得作为候选。paragraph 不需要分页。
公开 `read` 不提供分页参数；默认读取整个 list/table，便于模型在一次 read 后完整判断当前对象是否值得作为候选。paragraph 不需要分页。

### `add_candidate_evidence`

`add_candidate_evidence` 用来把一个显式 `evidence://` block link 指向的 paragraph/list/table 对象保存到一个 schema 字段的候选 evidence buffer，但不提交字段值：

```text
add_candidate_evidence(field_id, path_id="evidence://0001.0002.0001")
```

它解决的是“模型看到一个可能有用的对象，但还没完全决定字段值或 enum 分类”的场景。只要某个 paragraph/list/table evidence link 可能是字段证据，就可以调用 `add_candidate_evidence` 把这个对象记录为候选 block evidence，不等字段值或 enum decision 最终确定；后续看到同一字段的更多证据时，再次调用 `add_candidate_evidence(field_id, path_id=...)` 追加到该字段的 evidence buffer。

`add_candidate_evidence` 按 evidence link 寻址，不依赖 read 状态：

```text
paragraph:
  add_candidate_evidence(field_id="founded_year", path_id="evidence://0001.0002.0001")

list:
  add_candidate_evidence(field_id="service_items", path_id="evidence://0001.0002.0002")

table:
  add_candidate_evidence(field_id="fees", path_id="evidence://0001.0002.0003")
```

如果一个对象可能支持多个字段，不要在同一次工具调用里批量保存；应分别调用多次 `add_candidate_evidence`。如果一个字段需要多个 block，也应每个 block 调用一次。常规候选保存可以静默；只有候选改变证据图景、完成一组关键候选，或者相关性不明显时，assistant content 才需要用自然短句解释。解释里如果引用原文，短原文必须写成指向该 block 的 Markdown evidence link。这样 trace 会呈现“看到相关对象就记候选笔记，必要时再解释”的节奏，而不是每个工具动作都说话。`add_candidate_evidence` 成功后不改变阅读权限；它只更新字段候选 evidence buffer，并让该字段已有 review snapshot 失效。

`add_candidate_evidence` 做即时校验：

- `field_id` 必须存在于用户 schema。
- 每次调用必须提供一个 `path_id` 参数，参数值必须是 `evidence://` block link。
- evidence link 必须指向 paragraph/list/table 文件，不能是根、文档目录、section 目录或 inline selector。
- `add_candidate_evidence` 只接受 block selector，不接受 `sentences/items/rows` inline selector。
- 校验通过后，工具会保存 block selector，例如 `{"path_id": "0001.0002.0001"}`。

如果字段值已经通过 `write_field` 写过，后续 `add_candidate_evidence` 只会更新该字段的候选 evidence buffer，并让已有 review snapshot 失效；它不会自动改写字段结果里的最终 evidence。模型需要重新 `review_evidences`，再用 `write_field` 覆盖字段值和 `final_evidence`。

### `review_evidences`

`review_evidences` 是只读的字段证据复核工具。它返回一个字段的 schema 描述、当前字段值、已保存的候选 block evidence，以及这些 block 展开后的 inline selector 和 `evidence_texts`，帮助模型在写字段前重新判断“候选对象里的哪些句子、列表项或表格行应该进入最终 evidence”。

```text
review_evidences(field_id)
  -> 校验 field_id 是否存在
  -> 读取该字段当前 field buffer 和 evidence buffer
  -> paragraph block 展开为 {"path_id": ..., "sentences": ["S001", ...]}
  -> list block 展开为 {"path_id": ..., "items": ["I001", ...]}
  -> table block 展开为 {"path_id": ..., "rows": ["R001", ...]}
  -> 返回 field description、current value/status、candidate_evidence、evidence、evidence_texts 和简短 guidance
```

`review_evidences` 不做自动判决，也不替模型打分。它只把模型自己已经记录候选/写入的状态重新展示出来；模型复核后如果觉得证据足够支撑字段决定，就可以用 `write_field(... final_evidence ...)` 覆盖字段值；如果不够，就继续浏览并用显式 `add_candidate_evidence(path_id=...)` 补充候选证据。普通 review 检查不需要 assistant content；当 review 改变计划、发现证据不足或需要解释为什么继续读时，再输出阶段性说明；如果下一步显然是写同一字段，review content 可以为空，把用户可见结论留给 `write_field`。代码层面使用硬规则：`write_field.final_evidence` 必须来自同字段当前 `review_evidences` snapshot 返回的 inline selector 子集；如果 review 后又对同字段 `add_candidate_evidence`，该字段 review snapshot 会失效，必须重新 review 后再写。missing 字段或 null enum variant 可以使用空 `final_evidence`，但仍需要先有同字段 review snapshot，并由模型判断 review 结果足够支持“缺失/空值”这个决定。prompt 另外要求模型按紧凑字段决策簇推进，review 足够后下一轮通常写同字段，除非明确说明具体证据缺口。

### `write_field`

用户 schema 放在模型上下文里。模型按照 schema 从材料中抽取字段，并通过结果缓冲区增量写入字段值：

```text
write_field(field_id, value, final_evidence, status?)
```

`write_field` 的语义是“用 value 和 final_evidence 对某个 schema 字段做一次可覆盖的字段定案”。它不是候选记录工具，也不是数组追加工具；如果同一字段被再次写入，最终以最后一次为准。数组字段也通过 `write_field` 一次写入完整数组。

`final_evidence` 必须是 `review_evidences` 返回的 inline evidence 子集，不能使用 `add_candidate_evidence` 保存的 block selector。它让模型可以先用 `add_candidate_evidence` 记录宽一点的候选对象，再在 `review_evidences` 之后只提交真正保留的 Sxxx/Ixxx/Rxxx selector。真正保留指的是直接支撑提交值的 selector；只是同主题、背景、重复或弱相关的候选证据应当丢弃。只有 `null` 类型字段或 `null` enum variant 可以用 `final_evidence=[]` 表示“文档未提及/无最终证据”；非 `null` resolved 值必须在最终提交时带非空 `final_evidence`。

`status` 默认为 `resolved`。字段确实无法从材料中抽到时，可以写成 `missing`，并让 `submit_result` 根据 schema 判断是否允许缺失。`failed` 只用于系统或工具层失败，不应用来表达文档未提及。

`write_field` 做轻量即时校验：

- `field_id` 必须存在于用户 schema。
- `value` 必须是 JSON 可表示值。
- 任何写入都必须有同字段成功 `review_evidences` 产生的当前 snapshot；`status="missing"` 和 null enum variant 也不例外。
- `final_evidence` 必须能反查到原文，并且必须来自当前 `review_evidences(field_id)` snapshot 返回的 inline selector。
- `final_evidence` 不能是只有 `path_id` 的 block 级 selector。

完整 schema 校验不在写入阶段完成，而是在 `submit_result` 内部统一执行。`submit_result` 会读取最后一次 `write_field` 写入的字段值和 enum variant：如果字段是 `null` 类型或 enum variant 的 payload 类型是 `null`，允许空 `final_evidence`；其他 resolved 字段没有最终证据会返回 `MISSING_FINAL_EVIDENCE`，要求模型补证据或改成合法的空值/缺失表达。

证据 selector 统一使用：

```json
[
  {
    "path_id": "0001.0001.0001",
    "sentences": ["S001"]
  },
  {
    "path_id": "0001.0002.0004",
    "items": ["I002", "I002.001"]
  },
  {
    "path_id": "0001.0003.0002",
    "rows": ["R002", "R078"]
  }
]
```

校验规则：

```text
.md
  -> evidence 必须使用 sentences
  -> sentence 编号必须来自 review_evidences 展开的 paragraph block

.list
  -> evidence 必须使用 items
  -> item 编号必须来自 review_evidences 展开的 list block

.table
  -> evidence 必须使用 rows
  -> row 编号必须来自 review_evidences 展开的 table block
```

### `submit_result`

`submit_result` 是唯一最终提交入口。它读取当前 result buffer，执行内部校验：

```text
当前 result buffer + 用户 schema
  -> 校验必填字段是否都已写入
  -> 校验字段类型、enum、数组 item 和对象结构
  -> 校验证据是否满足字段规则
  -> 校验 evidence selector 是否能反查到原文句子、列表项或表格行
  -> 通过则返回 final result
  -> 失败则返回结构化错误，模型继续修正字段
```

错误返回示例：

```json
{
  "ok": false,
  "errors": [
    {
      "field_id": "founded_year",
      "code": "TYPE_MISMATCH",
      "message": "expected integer, got string",
      "current_value": "2020"
    },
    {
      "field_id": "company_name",
      "code": "MISSING_FINAL_EVIDENCE",
      "message": "final_evidence is required for resolved non-null values"
    }
  ]
}
```

不需要向模型暴露独立的 `validate_result` 工具；校验是 `submit_result` 的内部步骤。

## Schema 定位

schema 是用户给定的抽取目标定义，用于说明要抽哪些字段、字段类型、是否必填、证据要求和数组 item 结构。schema 不放入虚拟文件树，也不提供写工具。

示例：

```json
{
  "fields": [
    {
      "id": "company_name",
      "type": "string",
      "required": true,
      "description": "公司名称",
      "evidence": "required"
    },
    {
      "id": "founded_year",
      "type": "integer",
      "required": false,
      "description": "成立年份",
      "evidence": "required"
    },
    {
      "id": "main_risks",
      "type": "array<object>",
      "description": "主要风险",
      "evidence": "per_item",
      "items": {
        "risk": "string",
        "level": "low|medium|high"
      }
    }
  ]
}
```

schema 和材料树分离后，模型的职责更清楚：

```text
schema
  -> 告诉模型要抽什么

tree/read
  -> 告诉模型从哪里读

add_candidate_evidence
  -> 用显式 evidence:// block links 把可能相关的 paragraph/list/table 对象放入字段候选池

review_evidences/write_field/submit_result
  -> 展开候选 block 为 inline selector，再按 schema 写入字段值和 final_evidence 并提交结果
```

resolution prompt 要求模型用 `add_candidate_evidence` 把可能相关的可读 `evidence://` block link 记成候选 block evidence，但不强制 `read` 后立刻记录或跳过。字段写入必须基于同字段当前 `review_evidences` snapshot，并且 `write_field(final_evidence=...)` 只能复制该 snapshot 返回的 inline evidence links。模型只有在 review 后判断证据足够支撑字段值、或足够支撑 missing/null 决定时才写；否则继续读或继续添加候选证据。`write_field` 不设置固定读写次数或读量预算；当前硬约束集中在“final_evidence 来源于当前 review snapshot，新增同字段候选后 snapshot 失效”。read/candidate/review/write 顺序由工具说明和模型策略共同约束：模型应按紧凑字段决策簇推进，读到足够支持某字段的一组 block 后，优先完成候选保存、review 和 write，再切到无关阅读；review 足够后下一轮通常写同字段，除非明确说明具体证据缺口。

## 证据归因

inline 证据归因不依赖 quote 匹配、行号或列号，而依赖“`path_id` + 文件内编号”：

```text
read(evidence://paragraph_path_id)
  -> 模型理解段落正文
  -> 如果可能支持字段，add_candidate_evidence(field_id, path_id=evidence://paragraph_path_id) 保存 paragraph block
  -> 如果完全无关，直接继续读下一个对象或进入 review/write

read(evidence://list_path_id)
  -> 模型理解完整 list 及 Ixxx item 编号
  -> 如果可能支持字段，add_candidate_evidence(field_id, path_id=evidence://list_path_id) 保存 list block

read(evidence://table_path_id)
  -> 模型理解完整 table 及 Rxxx row 编号
  -> 如果可能支持字段，add_candidate_evidence(field_id, path_id=evidence://table_path_id) 保存 table block

review_evidences(field_id)
  -> 把候选 block 展开为 Sxxx/Ixxx/Rxxx inline selector 和 evidence_texts

write_field(field_id, value, final_evidence)
  -> 字段值使用同字段当前 review snapshot 复制的 inline final_evidence 完成定案
```

这样可以避免三类问题：

- 模型传入的 quote 和原文标点、空白或字词不一致。
- paragraph 的 `read` 默认返回句子编号导致 token 膨胀；句子编号延后到 `review_evidences` 展开候选时出现。
- 用户看到的证据文本由模型自由改写，无法验证。

证据文本必须能从 selector 反查回原文。`write_field` 是字段定案阶段，模型通常在同轮 assistant content 里解释为什么使用该证据；字段最终证据只能引用 `.md` 的 `Sxxx`、`.list` 的 `Ixxx` 或 `.table` 的 `Rxxx`。assistant content 里的展示引用可以在必要时引用整个 paragraph/list/table block，但 `final_evidence` 仍必须是 inline selector。

`add_candidate_evidence` 会在字段候选 evidence buffer 中保留 block selector。`review_evidences` 用 `HtmlDocument.inline_selector_for_path()` 把 block 展开成 inline selector，再用 `HtmlDocument.evidence_texts()` 生成 `evidence_texts`。`write_field` 输出字段对象时只带上 `final_evidence` 和对应的 `evidence_texts`。`evidence_texts` 是系统从 selector 反查出的只读文本，方便前端回放和实验 scorer 使用；它不是模型手写证据，也不作为模型可编辑输入。

## 结果形态

最终结果以字段对象数组为主，保留字段状态、字段值、证据引用和最后一次写入字段时的用户可见说明：

```json
{
  "fields": [
    {
      "field_id": "company_name",
      "status": "resolved",
      "value": "Acme Inc.",
      "evidence": [
        {
          "path_id": "0001.0001.0001",
          "sentences": ["S001"]
        }
      ],
      "evidence_texts": [
        {
          "path_id": "0001.0001.0001",
          "selector": "S001",
          "text": "公司名称为 Acme Inc."
        }
      ],
      "reason": "S001 给出公司名称。"
    },
    {
      "field_id": "founded_year",
      "status": "resolved",
      "value": 2020,
      "evidence": [
        {
          "path_id": "0001.0001.0002",
          "sentences": ["S001"]
        }
      ],
      "evidence_texts": [
        {
          "path_id": "0001.0001.0002",
          "selector": "S001",
          "text": "公司成立于2020年。"
        }
      ],
      "reason": "S001 写明公司成立于2020年。"
    }
  ]
}
```

如果字段没有抽到，应由结果层明确表示 `missing` 状态或在 `submit_result` 中返回必填错误。缺失解释可以作为模型说明展示，但不能伪装成系统已经穷尽检查过所有材料。

## 非目标

本架构暂不包含：

- 不创建真实文件或目录。
- 不支持编辑 HTML 或把抽取结果写回 HTML。
- 不提供 `search` 或 `stat` 作为第一版核心工具。
- 不把 title 作为可读文件。
- 不把 schema 放进材料文件树。
- 不提供写 schema 工具。
- 不提供数组追加工具；数组字段也用 `write_field` 写入完整值。
- 不暴露 `validate_result` 工具。
- 不让模型自由书写面向用户的 plan 作为可解释性依据。

可解释性应来自真实工具调用、可反查 evidence selector 和 `submit_result` 的结构化校验，而不是来自模型自述的计划文本。
