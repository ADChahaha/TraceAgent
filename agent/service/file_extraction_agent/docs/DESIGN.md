# File Extraction Agent Design

本文记录 `file_extraction_agent` 当前的架构方向：把语义 HTML 暴露成只读虚拟文件树，让模型按用户给定 schema 从多文件文档中抽取字段，并用 paragraph 句子编号、list item 编号和 table row 编号做 inline 证据归因。

本文不设计模型自由书写的 plan 或面向用户的计划叙事。

## 核心思路

抽取链路分成三层：

```text
用户给定 schema + 多个语义 HTML 文件
  -> 构建只读 semantic HTML virtual tree
  -> 模型用 tree/read 浏览文件、章节和段落
  -> 模型用 anchors 给 paragraph 取得句子编号，用 read/query_table 中的编号引用 list item 和 table row
  -> 模型用 write_field 增量写入字段结果
  -> submit_result 内部按 schema 校验并返回最终结果或错误
```

`schema` 是用户给定的抽取契约，直接放在模型上下文里，不作为虚拟文件树的一部分，也不提供写 schema 工具。虚拟文件树只表达待抽取材料；字段结果通过专门的结果写入工具提交。

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
└── 001-file1-项目设计说明/
    ├── 001-背景/
    │   ├── 001-这个项目最初是为了.md
    │   └── 002-后来我们发现模型.md
    └── 002-实现方案/
        ├── 001-系统会先解析HTML.md
        ├── 002-关键步骤.list
        ├── 003-费用明细.table
        └── 004-虚拟树不会落盘.md
```

编号是路径稳定性的基础：

- 文档目录使用 `001-...`、`002-...` 区分多个输入文件。
- section 目录使用同级编号区分相同 header。
- paragraph、list 和 table 文件使用同级编号保留原文 block 顺序并避免 snippet 重复。

路径是模型可读的定位界面，不是内部唯一主键。内部仍应保存 `node_id`、源 HTML 节点、原始文件信息和必要的 source range，便于工具从路径反查原文。

## 工具边界

面向模型的最小工具集合：

```text
tree(path="/", depth=3, reason)
read(path, offset?, limit?, reason)
anchors(path, reason)
query_table(path, sql, offset?, limit?, reason)
write_field(field_id, value, evidence, status?, reason)
submit_result(reason?)
```

所有模型主动浏览、读取、查询和写入工具都必须带 `reason`。`reason` 是用户可见的动作说明，用来解释“为什么现在展开这个目录、读取这个文件、查询这张表或写入这个字段”。它不是模型推理链，也不是证据本身；可信证据只来自虚拟路径和文件内编号。

### `tree`

`tree` 返回虚拟文件树的目录和 paragraph 文件名，是模型进入材料空间的入口。

```text
tree("/", depth=1, reason="先查看有哪些输入文档。")
  -> 返回所有文档目录

tree("/001-file1-项目设计说明", depth=2, reason="展开项目设计说明，定位实现相关章节。")
  -> 返回该文档下的 section 和 paragraph/list/table 文件
```

`tree` 不返回 paragraph 正文，不返回 schema，也不承担搜索职责。

### `read`

`read` 按虚拟文件类型返回 Markdown 阅读视图。paragraph 默认返回完整正文，不带句子编号；list 和 table 默认带 item/row 编号，方便字段证据直接绑定到文件内编号。

```text
read("/001-file1-项目设计说明/002-实现方案/001-系统会先解析HTML.md", reason="读取实现方案段落，确认语义树生成方式。")
  -> "系统会先解析 HTML，并按 heading 层级生成语义树。..."
```

list 返回 Markdown list，前置少量 metadata，并给每个 item 稳定编号：

```markdown
---
kind: list
path: /001-file1-项目设计说明/002-实现方案/002-关键步骤.list
title: 关键步骤
items: 3
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
path: /001-file1-项目设计说明/002-实现方案/003-费用明细.table
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

`offset` 和 `limit` 用于 list/table 分页，默认限制返回数量，避免大列表或大表一次性膨胀上下文。paragraph 不需要分页。

### `anchors`

`anchors` 只用于 paragraph，对已定位的 `.md` 文件返回轻量句子编号。list 和 table 不需要 `anchors`，因为 `read` 和 `query_table` 已经在 Markdown 视图中暴露 `Ixxx` 和 `Rxxx` 编号。

```text
paragraph path
  -> 读取 paragraph 原文
  -> 按句子边界切分
  -> 为每个句子生成 Sxxx 编号
  -> 返回句子编号和短 preview
```

示例返回：

```json
[
  {
    "id": "S001",
    "preview": "系统会先解析 HTML，并按 heading..."
  },
  {
    "id": "S002",
    "preview": "解析结果不会落盘，而是作为虚拟..."
  }
]
```

第一版证据粒度以 sentence 为主，不默认切到 clause。clause 切分在中文、英文和技术文本中容易过度破碎，可以作为后续增强。

### `query_table`

`query_table` 是 `.table` 文件的辅助读取工具，用于大表或需要按条件定位行的场景。它只接受 table 虚拟路径，不接受 section id 或原始 HTML id。

```text
query_table(path, sql, offset?, limit?, reason)
  -> 校验 path 是 .table 文件
  -> 校验 SQL 是单条安全 SELECT，表名固定为 data
  -> 执行查询并保留原始 Rxxx 行编号
  -> 返回带 metadata 的 Markdown table
```

示例返回：

```markdown
---
kind: table_query
path: /001-file1-项目设计说明/002-实现方案/003-费用明细.table
sql: SELECT "项目", "金额" FROM data WHERE "项目" LIKE '%押金%'
matched_rows: 2
showing: 1-2
---

| row | 项目 | 金额 |
| --- | --- | --- |
| R002 | 押金 | 500 |
| R078 | 押金退还 | -500 |
```

字段证据可以直接引用 query 结果里出现的 `Rxxx` 行编号。`query_table` 不是最终提交入口；它只帮助模型定位和阅读表格行。

### `write_field`

用户 schema 放在模型上下文里。模型按照 schema 从材料中抽取字段，并通过结果缓冲区增量写入：

```text
write_field(field_id, value, evidence, status?, reason)
```

`write_field` 的语义是“用 value + evidence 对某个 schema 字段做一次可覆盖的字段定案”。它不是候选记录工具，也不是数组追加工具；如果同一字段被再次写入，最终以最后一次为准。数组字段也通过 `write_field` 一次写入完整数组。

`status` 默认为 `resolved`。字段确实无法从材料中抽到时，可以写成 `missing`，并让 `submit_result` 根据 schema 判断是否允许缺失。`failed` 只用于系统或工具层失败，不应用来表达文档未提及。

`write_field` 做轻量即时校验：

- `field_id` 必须存在于用户 schema。
- `value` 必须是 JSON 可表示值。
- `evidence` 必须使用合法的虚拟路径和文件内编号。

完整 schema 校验不在写入阶段完成，而是在 `submit_result` 内部统一执行。

证据 selector 统一使用：

```json
[
  {
    "path": "/001-file/001-概况/001-公司成立于2020年.md",
    "sentences": ["S001"]
  },
  {
    "path": "/001-file/002-条款/004-服务范围.list",
    "items": ["I002", "I002.001"]
  },
  {
    "path": "/001-file/003-费用/002-费用明细.table",
    "rows": ["R002", "R078"]
  }
]
```

校验规则：

```text
.md
  -> evidence 必须使用 sentences
  -> sentence 编号必须来自 anchors(path)

.list
  -> evidence 必须使用 items
  -> item 编号必须存在于该 list

.table
  -> evidence 必须使用 rows
  -> row 编号必须存在于该 table，且可以来自 read 或 query_table 的阅读结果
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
      "code": "MISSING_EVIDENCE",
      "message": "evidence is required"
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

anchors/read/query_table
  -> 给出 paragraph 句子编号、list item 编号和 table row 编号，说明字段凭什么成立

write_field/submit_result
  -> 让模型按 schema 写入并提交结果
```

## 证据归因

inline 证据归因不依赖 quote 匹配、行号或列号，而依赖“虚拟路径 + 文件内编号”：

```text
read(paragraph_path)
  -> 模型理解段落正文

anchors(paragraph_path)
  -> 工具给出该段落的 Sxxx 句子编号和短 preview

read(list_path)
  -> Markdown list 中直接显示 Ixxx item 编号

read(table_path) 或 query_table(table_path, sql)
  -> Markdown table 中直接显示 Rxxx row 编号

write_field(field_id, value, evidence)
  -> 字段值绑定到可反查的 path + Sxxx/Ixxx/Rxxx
```

这样可以避免三类问题：

- 模型传入的 quote 和原文标点、空白或字词不一致。
- paragraph 的 `read` 默认返回句子编号导致 token 膨胀。
- 用户看到的证据文本由模型自由改写，无法验证。

证据文本必须能从 selector 反查回原文。模型可以用 `reason` 解释为什么使用该证据，但字段证据只能引用 `.md` 的 `Sxxx`、`.list` 的 `Ixxx` 或 `.table` 的 `Rxxx`。

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
          "path": "/001-file/001-概况/001-公司名称.md",
          "sentences": ["S001"]
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
          "path": "/001-file/001-概况/002-公司成立于2020年.md",
          "sentences": ["S001"]
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
