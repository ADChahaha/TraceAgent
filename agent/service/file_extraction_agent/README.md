# file_extraction_agent

HTML-based document field extraction agent.

输入是 `document_processor` 产出的语义 HTML。这里先为 HTML 建索引，再用 LangGraph 工具把证据读出来，最后把每个字段写成 `resolved` 或 `failed`，并把全过程放进 `trace`。

## 工作链路

```text
html + task_spec + run_options
  -> input_adapter 校验输入并构造 HtmlExtractionInput
  -> html_index 基于已有 id 构建 document.tree / elements_by_id / tables_by_id / row_index
  -> broad_new 仅保留兼容占位 BroadPlan
  -> resolution_new 生成任务提示并挂载工具
  -> overview 先给出混排 outline
  -> read_section / read_blocks / read_block_range / read_list / query_table 读取证据
  -> set_field 写入字段值或失败原因
  -> finish 做最终完整性校验
  -> ExtractionResult.result + trace
```

`document.tree` 不是纯标题树。它按 DOM 里的语义容器组织 outline：`section` 才拥有自己的子节点；和 heading 平级的 `p`、`ul`/`ol`、`table` 会保持同层 item，不会被默认算进前一个 heading。

## 工具

| Tool | 作用 |
| --- | --- |
| `update_plan(plan_index, status, reason)` | 只用于 replay broad 计划状态。 |
| `overview()` | 返回混排 outline，包含 `section`、heading、`p`、list、table 的可读摘要。 |
| `read_section(section_id, reason)` | 只读 heading 自身真实后代的 block previews；平级块由 overview 直接暴露。 |
| `read_blocks(section_id, indexes, reason)` | 按模型选择的 index 列表读取离散块；scope 可以是 `section` 容器、heading 真实后代，或单个叶子块 id。 |
| `read_block_range(section_id, start_index, count, reason)` | 从 `start_index` 开始连续读取 `count` 个块，用于顺序补上下文。 |
| `read_list(section_id, block_offset, item_offset, number, reason)` | 对 list block 分页读取 list item；overview 里的顶层 list id 可直接配 `block_offset=0` 使用。 |
| `query_table(section_id, block_offset, sql, reason)` | 对 table block 执行安全 SELECT；overview 里的顶层 table id 可直接配 `block_offset=0` 使用。 |
| `set_field(name, value, evidence_ids, reason, status, failure_reason)` | 写字段值或失败状态。 |
| `finish()` | 校验所有字段是否已完成。 |

## 读取规则

`read_section`
  -> 只接受 heading 节点
  -> 只读该 heading 元素真实包含的后代块，不把后面的平级 `p` / list / table 算进去
  -> 如果章节太长，工具内部会触发隔离 scoped reader

`read_blocks`
  -> 接受 section 容器、heading、或叶子块 id
  -> 用 indexes 列表读取模型从 overview/read_section 预览中选中的离散块；非连续证据优先用它
  -> 如果需要连续扫一段上下文，改用 read_block_range，避免把连续窗口塞成很长 indexes 列表
  -> 普通 `p` 直接返回完整文本 HTML
  -> `ul` / `ol` 可以返回 `list-ref`；如果 overview 已给出 list id，也可以直接用 `read_list`
  -> `table` 可以返回 `table-ref`；如果 overview 已给出 table id，也可以直接用 `query_table`

`read_block_range`
  -> 接受和 `read_blocks` 相同的 scope
  -> 用 `start_index + count` 连续读取一段上下文，最多按工具上限返回 20 个块
  -> 返回结构仍包含实际 `indexes`，方便 replay 看清模型读了哪些块

最上层 `p` 可以直接这样读：

```text
overview()
  -> item_id="dp-p-1", type="TEXT", parent_section_id="", read_with="read_blocks"

read_blocks("dp-p-1", [0], reason)
  -> 返回这个 p 的完整内容
```

section 下面的 `p` 也一样可以直接按块 id 读取；如果想按父容器顺序读，就先看 overview 里的 section 容器 id，再用 `read_blocks(section_id, [1, 3], reason)` 读取选中的块。和 heading 平级的 `p` 不需要、也不会通过前一个 heading 来读。

连续扫上下文时这样读：

```text
read_block_range("dp-page-1", 4, 6, reason)
  -> 返回 dp-page-1 scope 里 index 4 到 9 的块
```

顶层 list 可以直接这样读：

```text
overview()
  -> item_id="dp-ul-1", type="LIST", read_with="read_list", block_offset=0

read_list("dp-ul-1", 0, 0, 20, reason)
  -> 返回 list items 和 evidence_ids
```

顶层 `table` 可以直接这样查：

```text
overview()
  -> item_id="dp-table-1", type="TABLE", read_with="query_table", block_offset=0

query_table("dp-table-1", 0, "SELECT ... FROM data", reason)
  -> 返回匹配 rows 和 evidence_ids
```

## 追踪

每次工具调用都会进入 `trace.actions`，字段最终结果会进入 `trace.field_states`。这样 backend 和 frontend 不需要猜模型到底看了什么，只需要回放 action 就行。

## 公共入口

```python
from service.file_extraction_agent.processor import extract

result = extract(
    html='<p id="dp-p-1">正文</p>',
    task_spec={"fields": [{"name": "title", "type": "string", "required": True}]},
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "broad_model_name": "...",
        "resolution_model_name": "...",
    },
    run_options={"max_tool_calls": 40},
)
```

更完整的实现边界和设计说明见 [docs/DESIGN.md](docs/DESIGN.md)。
