# File Extraction Agent Design

本文记录 `file_extraction_agent` 当前的架构方向：把语义 HTML 暴露成只读虚拟文件树，让模型按用户给定 schema 从多文件文档中抽取字段，并用 paragraph 句子编号、list item 编号和 table row 编号做 inline 证据归因。

本文不设计模型自由书写的 plan 或面向用户的计划叙事。

## 核心思路

抽取链路分成三层：

```text
用户给定 schema + 多个语义 HTML 文件
  -> 构建只读 semantic HTML virtual tree
  -> resolution 初始上下文写入 root depth=3 的导航树
  -> 模型用初始树和 tree/read 浏览文件、章节和段落
  -> 每个 reason 先分析上一轮 action 结果，再说明本轮准备调用什么工具
  -> read 成功后进入 pending judgement 状态，模型必须先判断当前对象是否可能支持某个 schema 字段
  -> 如果当前 paragraph/list/table 可能支持字段，紧跟 bind_evidence 把这个刚读到的对象绑定为候选 block evidence
  -> 如果当前对象不相关，紧跟 skip_read 关闭这次 read 判断，再继续浏览
  -> 模型用 review_evidences 复看某字段的候选 block evidence，并由工具展开成 Sxxx/Ixxx/Rxxx inline selector
  -> 模型紧跟 write_field 提交同一字段的字段值或 enum decision，并且 final_evidence 只能复制刚刚 review_evidences 返回的 inline selector
  -> submit_result 内部按 schema 校验并返回最终结果或错误
```

`schema` 是用户给定的抽取契约，直接放在模型上下文里，不作为虚拟文件树的一部分，也不提供写 schema 工具。虚拟文件树只表达待抽取材料；字段结果通过专门的结果写入工具提交。

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
[0000] /
└── [0000.0001] file1-项目设计说明/
    ├── [0000.0001.0001] 背景/
    │   ├── [0000.0001.0001.0001] 这个项目最初是为了.md
    │   └── [0000.0001.0001.0002] 后来我们发现模型.md
    └── [0000.0001.0002] 实现方案/
        ├── [0000.0001.0002.0001] 系统会先解析HTML.md
        ├── [0000.0001.0002.0002] 关键步骤.list
        ├── [0000.0001.0002.0003] 费用明细.table
        └── [0000.0001.0002.0004] 虚拟树不会落盘.md
```

编号是路径稳定性的基础：

- 文档目录使用 `001-...`、`002-...` 区分多个输入文件。
- section 目录使用同级编号区分相同 header。
- paragraph、list 和 table 文件使用同级编号保留原文 block 顺序并避免 snippet 重复。

这些 `001-` / `002-` 同级编号只存在于内部 raw path。模型可见的 `tree` 行已经有 `path_id` 承担去重和定位职责，所以显示名会去掉同级编号前缀，避免重复噪音。显示名还会 percent-decode，例如把 `Confidentiality%20Agreement` 显示为 `Confidentiality Agreement`；内部 raw path 保持原样，避免破坏已有索引兼容。

raw virtual path 是内部索引，不再作为模型可见 locator。`HtmlDocument` 会同时维护 `nodes_by_path` 和 `nodes_by_path_id`：raw path 用于内部调试和兼容底层查询，`path_id` 用于 tree/read/review/write 的模型交互。`path_id` 按树位置生成，例如根为 `[0000]`，第一个文档为 `[0000.0001]`，文档下第一个 section 为 `[0000.0001.0001]`。

模型只能复制 tree 输出里的 `path_id`，不能手写、URL encode 或猜 raw virtual path。工具返回、候选 evidence buffer、`review_evidences.evidence`、`write_field(final_evidence=...)` 和最终结果都使用 `path_id` selector；原文文本由系统通过 `path_id + Sxxx/Ixxx/Rxxx` 反查。

## 工具边界

面向模型的最小工具集合：

```text
tree(path_id="[0000]", depth=3, reason)
read(path_id, offset?, limit?, reason)
bind_evidence(field_id?, bindings?, reason)
skip_read(reason)
review_evidences(field_id, reason)
write_field(field_id, value, final_evidence, status?, reason)  # 必须紧跟同字段 review_evidences
submit_result(reason?)
```

系统 prompt 只描述 agent 角色、抽取流程、`reason` 语义和 evidence lifecycle；具体工具参数约束写在各 tool description 中，并通过 LangGraph `bind_tools` 暴露给模型。这样模型在选择某个工具时能直接看到该工具的局部规则，例如 `read` 只能读取 tree 输出中 `.md/.list/.table` 文件对应的 `path_id`，目录 `path_id` 必须先用 `tree` 展开。

所有模型主动浏览、读取、查询和写入工具都必须带 `reason`。`reason` 是用户可见的动作说明，用来解释“上一轮 action 说明了什么、所以这一轮准备调用什么工具”。它不是模型推理链，也不是证据本身；可信证据只来自虚拟路径和文件内编号。

resolution system prompt 明确要求模型每个 assistant turn 只发一个 tool call，不能在同一轮返回多个或并行 tool calls，并且必须等待该工具结果回来后再决定下一步。resolution graph 也做同样的运行时兜底：即使模型一次返回多个 tool calls，运行时也只保留第一个交给工具节点执行，强制模型在看到上一轮工具结果后再决定下一步，避免一次性批量 `read` 多个路径而绕过“读到可能证据就绑定”的流程。

`reason` 的最小结构是：

```text
上一轮 action 结果
  -> 判断它是否指向某个 schema 字段
  -> 本轮准备调用的工具和目的
```

如果上一轮是 `read`，下一步只能是 `bind_evidence` 或 `skip_read`。`reason` 必须明确说明刚读到的 paragraph/list/table 是否可能支持某个字段：可能支持就 `bind_evidence`，完全不相关才 `skip_read`。在这次判断关闭之前，模型不能继续 `read`、`tree`、`review_evidences`、`write_field` 或 `submit_result`。这个约束让模型不能连续扫很多内容后靠隐式记忆直接写答案。

候选证据绑定是 provisional collection，不是最终字段分类或定案。`bind_evidence` 只绑定刚刚 `read` 的一个对象，保存的是 block 级候选 evidence，不接受模型手写任意 `path_id`，也不接受 Sxxx/Ixxx/Rxxx inline selector。模型看到当前 `read` 结果可能支持或反驳某个字段时，必须先把该对象绑定进候选集合，再继续检查其他 supporting、qualifying 或 contrary clauses；不能为了继续读其他路径而推迟当前对象的判断。这条工具节奏由 resolution prompt 和 tool description 统一负责，`task_spec` 只描述字段语义和输出类型，不负责说明工具调用顺序。

### `tree`

resolution 的初始 human message 会直接包含 `tree("[0000]", depth=3)` 等价的导航树。这个初始树不需要模型主动调用工具，层级覆盖根目录、文档目录、一级 section，以及一级 section 下的 paragraph/list/table 文件：

```text
[0000] /
  -> [0000.0001] 文档目录/
  -> [0000.0001.0001] 一级 section/
  -> [0000.0001.0001.0001] 可读 paragraph/list/table 文件
```

这样当 OCR 或语义解析把实质条款挂到标题看似无关的目录下时，模型一开始也能看到该目录下的可读文件。`tree` 工具仍然保留，用于继续展开更深层 section；初始树和 `tree` 只提供导航，不返回 paragraph 正文，不作为最终 evidence。

`tree` 返回虚拟文件树的目录和 paragraph 文件名，是模型继续展开更深目录的入口。

```text
tree("[0000]", depth=1, reason="先查看有哪些输入文档。")
  -> 返回所有文档目录

tree("[0000.0001]", depth=2, reason="展开项目设计说明，定位实现相关章节。")
  -> 返回该文档下的 section 和 paragraph/list/table 文件
```

`tree` 不返回 paragraph 正文，不返回 schema，也不承担搜索职责。

### `read`

`read` 按虚拟文件类型返回 Markdown 阅读视图。paragraph 默认返回完整正文，不带句子编号；list 和 table 默认带 item/row 编号，便于模型判断这个对象是否可能支持字段。`read` 成功后会在内部记录一个 pending read judgement：模型必须先用 `bind_evidence` 或 `skip_read` 关闭这个判断，才能继续调用其他工具。

```text
read("[0000.0001.0002.0001]", reason="读取实现方案段落，确认语义树生成方式。")
  -> "系统会先解析 HTML，并按 heading 层级生成语义树。..."
```

pending read 的状态机是：

```text
read(path_id)
  -> pending_read = 当前 paragraph/list/table 对象
  -> bind_evidence(field_id 或 bindings)  # 当前对象可能支持字段，保存 block 候选并关闭 pending_read
     或 skip_read(reason)     # 当前对象完全不相关，记录跳过并关闭 pending_read
  -> tree/read/review_evidences/write_field/submit_result 才能继续
```

如果 pending read 未关闭就调用其他工具，工具返回 `READ_JUDGEMENT_REQUIRED`。如果没有 pending read 却调用 `bind_evidence` 或 `skip_read`，工具返回 `READ_REQUIRED`。

list 返回 Markdown list，前置少量 metadata，并给每个 item 稳定编号：

```markdown
---
kind: list
path_id: [0000.0001.0002.0002]
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
path_id: [0000.0001.0002.0003]
title: 费用明细
rows: 238
columns: 项目 | 金额 | 日期
showing: 1-30
---

| row | 项目 | 金额 | 日期 |
| --- | --- | --- | --- |
| R001 | 服务费 | 1000 | 2024-01-01 |
| R002 | 押金 | 500 | 2024-01-02 |
```

`offset` 和 `limit` 用于 list/table 显式分页；默认读取整个 list/table，便于模型在一次 read 后完整判断当前对象是否值得绑定。paragraph 不需要分页。

### `bind_evidence`

`bind_evidence` 用来把刚刚 `read` 的 paragraph/list/table 对象绑定到一个或多个 schema 字段，但不提交字段值：

```text
bind_evidence(field_id, reason)
bind_evidence(bindings=[{"field_id": "..."}], reason)
```

它解决的是“模型刚读到一个可能有用的对象，但还没完全决定字段值或 enum 分类”的场景。模型读取 paragraph/list/table 后，只要认为当前对象可能是某个字段的证据，就应立刻调用 `bind_evidence` 把这个对象记录为候选 block evidence，不等字段值或 enum decision 最终确定；后续读到同一字段的更多证据时，再次按 `read -> bind_evidence` 链路追加到该字段的 evidence buffer。

`bind_evidence` 只能使用当前 pending read：

```text
paragraph:
  read(.md)
  -> bind_evidence(field_id)

list:
  read(.list)
  -> bind_evidence(field_id)

table:
  read(.table)
  -> bind_evidence(field_id)
```

如果当前对象可能支持多个字段，应在同一次工具调用里使用 `bindings=[{"field_id": ...}, ...]` 把这个 block 绑定给多个字段。`bind_evidence` 成功后会关闭 pending read judgement；模型随后可以继续 `tree/read/review_evidences/write_field/submit_result`。如果 bind 后又想给同一个旧 read 追加字段，必须重新 `read` 该对象，这能避免模型隔多步后靠记忆回头绑定。换句话说，`bind_evidence` 不是按 path 寻址的证据搜索工具，它只是“把刚读到的这一块放进字段候选池”。

`bind_evidence` 做即时校验：

- `field_id` 必须存在于用户 schema。
- 当前必须存在未关闭的 pending read。
- pending read 必须是 paragraph/list/table 对象。
- 校验通过后，工具会保存 block selector，例如 `{"path_id": "[0000.0001.0002.0001]"}`。

如果字段值已经通过 `write_field` 写过，后续 `bind_evidence` 只会更新该字段的候选 evidence buffer，并让已有 review snapshot 失效；它不会自动改写字段结果里的最终 evidence。模型需要重新 `review_evidences`，再用 `write_field` 覆盖字段值和 `final_evidence`。

### `skip_read`

`skip_read` 是关闭 pending read judgement 的工具。它只用于刚读到的对象完全不支持任何 schema 字段时，记录“这个对象已判断为无关”，然后允许模型继续浏览。

```text
read(path_id)
  -> 模型判断当前对象完全不相关
  -> skip_read(reason)
  -> 可以继续 tree/read/review_evidences/write_field/submit_result
```

`skip_read` 不写字段、不写候选证据，也不参与最终结果。它的存在是为了避免模型在读到无关内容时被迫绑定假证据；同时也让每次 read 都有显式判断，避免连续阅读后直接靠隐式记忆写答案。

### `review_evidences`

`review_evidences` 是只读的字段证据复核工具。它返回一个字段的 schema 描述、当前字段值、已绑定候选 block evidence，以及这些 block 展开后的 inline selector 和 `evidence_texts`，帮助模型在写字段前重新判断“候选对象里的哪些句子、列表项或表格行应该进入最终 evidence”。

```text
review_evidences(field_id, reason)
  -> 校验 field_id 是否存在
  -> 读取该字段当前 field buffer 和 evidence buffer
  -> paragraph block 展开为 {"path_id": ..., "sentences": ["S001", ...]}
  -> list block 展开为 {"path_id": ..., "items": ["I001", ...]}
  -> table block 展开为 {"path_id": ..., "rows": ["R001", ...]}
  -> 返回 field description、current value/status、candidate_evidence、evidence、evidence_texts 和简短 guidance
```

`review_evidences` 不做自动判决，也不替模型打分。它只把模型自己已经绑定/写入的状态重新展示出来；模型复核后可以紧跟 `write_field(... final_evidence ...)` 覆盖字段值，或继续通过新的 `read -> bind_evidence` 补充候选证据。代码层面使用硬规则：每次 `write_field` 都必须紧跟同字段 `review_evidences`，并且 `final_evidence` 必须是这次 review 返回的 inline selector 子集。如果 review 后插入了任何其他工具调用，哪怕是失败的 write、另一个字段的 review、read 或 submit，都必须重新 review 同一字段再写。missing 字段或 null enum variant 可以使用空 `final_evidence`，但仍要在写入前紧跟同字段 review。

### `write_field`

用户 schema 放在模型上下文里。模型按照 schema 从材料中抽取字段，并通过结果缓冲区增量写入字段值：

```text
write_field(field_id, value, final_evidence, status?, reason)
```

`write_field` 的语义是“用 value 和 final_evidence 对某个 schema 字段做一次可覆盖的字段定案”。它不是候选记录工具，也不是数组追加工具；如果同一字段被再次写入，最终以最后一次为准。数组字段也通过 `write_field` 一次写入完整数组。

`final_evidence` 必须是 `review_evidences` 返回的 inline evidence 子集，不能使用 `bind_evidence` 保存的 block selector。它让模型可以先用 `bind_evidence` 记录宽一点的候选对象，再在 `review_evidences` 之后只提交真正保留的 Sxxx/Ixxx/Rxxx selector。真正保留指的是直接支撑提交值的 selector；只是同主题、背景、重复或弱相关的候选证据应当丢弃。只有 `null` 类型字段或 `null` enum variant 可以用 `final_evidence=[]` 表示“文档未提及/无最终证据”；非 `null` resolved 值必须在最终提交时带非空 `final_evidence`。

`status` 默认为 `resolved`。字段确实无法从材料中抽到时，可以写成 `missing`，并让 `submit_result` 根据 schema 判断是否允许缺失。`failed` 只用于系统或工具层失败，不应用来表达文档未提及。

`write_field` 做轻量即时校验：

- `field_id` 必须存在于用户 schema。
- `value` 必须是 JSON 可表示值。
- 任何写入都必须紧跟同字段成功 `review_evidences`；`status="missing"` 和 null enum variant 也不例外。
- `final_evidence` 必须能反查到原文，并且必须来自刚刚那次 `review_evidences(field_id)` 返回的 inline selector。
- `final_evidence` 不能是只有 `path_id` 的 block 级 selector。

完整 schema 校验不在写入阶段完成，而是在 `submit_result` 内部统一执行。`submit_result` 会读取最后一次 `write_field` 写入的字段值和 enum variant：如果字段是 `null` 类型或 enum variant 的 payload 类型是 `null`，允许空 `final_evidence`；其他 resolved 字段没有最终证据会返回 `MISSING_FINAL_EVIDENCE`，要求模型补证据或改成合法的空值/缺失表达。

证据 selector 统一使用：

```json
[
  {
    "path_id": "[0000.0001.0001.0001]",
    "sentences": ["S001"]
  },
  {
    "path_id": "[0000.0001.0002.0004]",
    "items": ["I002", "I002.001"]
  },
  {
    "path_id": "[0000.0001.0003.0002]",
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

bind_evidence
  -> 把刚读到且可能相关的 paragraph/list/table 对象放入字段候选池

skip_read
  -> 把刚读到但完全不相关的对象显式标记为已判断

review_evidences/write_field/submit_result
  -> 展开候选 block 为 inline selector，再按 schema 写入字段值和 final_evidence 并提交结果
```

resolution prompt 要求模型每次 `read` 后必须立刻判断当前对象：认为可能是字段证据就 `bind_evidence`，完全不相关就 `skip_read`，不要连续读取后再回头绑定。字段写入前必须紧跟同字段 `review_evidences`，并且 `write_field(final_evidence=...)` 只能复制刚刚 review 返回的 inline selector。`write_field` 不设置固定读写次数或读量预算；硬约束只在工具状态机上表达，即 read 后必须判断、write 前必须紧邻同字段 review。

## 证据归因

inline 证据归因不依赖 quote 匹配、行号或列号，而依赖“`path_id` + 文件内编号”：

```text
read(paragraph_path_id)
  -> 模型理解段落正文
  -> 如果可能支持字段，bind_evidence(field_id) 绑定当前 paragraph block
  -> 如果完全无关，skip_read()

read(list_path_id)
  -> 模型理解完整 list 及 Ixxx item 编号
  -> 如果可能支持字段，bind_evidence(field_id) 绑定当前 list block

read(table_path_id)
  -> 模型理解完整 table 及 Rxxx row 编号
  -> 如果可能支持字段，bind_evidence(field_id) 绑定当前 table block

review_evidences(field_id)
  -> 把已绑定 block 展开为 Sxxx/Ixxx/Rxxx inline selector 和 evidence_texts

write_field(field_id, value, final_evidence)
  -> 必须紧跟同字段 review_evidences，字段值使用从刚刚 review 复制的 inline final_evidence 完成定案
```

这样可以避免三类问题：

- 模型传入的 quote 和原文标点、空白或字词不一致。
- paragraph 的 `read` 默认返回句子编号导致 token 膨胀；句子编号延后到 `review_evidences` 展开候选时出现。
- 用户看到的证据文本由模型自由改写，无法验证。

证据文本必须能从 selector 反查回原文。模型可以用 `reason` 解释为什么使用该证据，但字段证据只能引用 `.md` 的 `Sxxx`、`.list` 的 `Ixxx` 或 `.table` 的 `Rxxx`。

`bind_evidence` 会在字段候选 evidence buffer 中保留 block selector。`review_evidences` 用 `HtmlDocument.inline_selector_for_path()` 把 block 展开成 inline selector，再用 `HtmlDocument.evidence_texts()` 生成 `evidence_texts`。`write_field` 输出字段对象时只带上 `final_evidence` 和对应的 `evidence_texts`。`evidence_texts` 是系统从 selector 反查出的只读文本，方便前端回放和实验 scorer 使用；它不是模型手写证据，也不作为模型可编辑输入。

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
          "path_id": "[0000.0001.0001.0001]",
          "sentences": ["S001"]
        }
      ],
      "evidence_texts": [
        {
          "path_id": "[0000.0001.0001.0001]",
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
          "path_id": "[0000.0001.0001.0002]",
          "sentences": ["S001"]
        }
      ],
      "evidence_texts": [
        {
          "path_id": "[0000.0001.0001.0002]",
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
