# file_extraction_agent

HTML-based document field extraction agent.

Input is semantic HTML produced by `document_processor`; all trackable elements must already have ids. The package builds a lightweight HTML index, runs a broad planning stage, and then runs a LangGraph resolution agent with document tools.

## Trace Tools

字段级追踪由工具调用直接产生。`graph` 会把 broad plan、plan 状态、字段状态和每次工具 action 放进 `ExtractionResult.trace`，backend 和 frontend 不需要猜测模型做过什么。

```text
html + task_spec
  -> return_broad_plan
  -> update_plan
  -> read_element / read_section
  -> table_extraction / paragraph_extraction
  -> set_field
  -> finish
  -> trace.actions + trace.field_states
```

| Tool | 什么时候调用 | 追踪粒度 | 追踪价值 |
| --- | --- | --- | --- |
| `return_broad_plan(summary, plan, risks)` | broad 阶段唯一允许调用的工具 | 任务级计划 | 记录抽取计划、字段阅读顺序和风险提示。 |
| `update_plan(plan_index, status, reason)` | resolution 开始或完成某个计划步骤时 | 计划步骤级 | 记录计划执行进度，让 replay 能显示当前步骤。 |
| `read_element(element_id, reason)` | 只需要读取一个确定 HTML 节点时 | 单个 HTML 元素级 | 按 `element_id` 读取一个小元素；普通元素返回该元素 HTML 和一个 evidence id，表格元素只返回 table-ref、列名和 SQL 提示，不返回表格数据行。 |
| `read_section(section_id, reason, depth)` | 需要读取一个标题下面的成段上下文时 | 文件树递归章节级 | `section_id` 必须是 heading；工具从该 heading 后面开始沿文档顺序递归收集内容，遇到同级或更高级 heading 停止；`depth` 控制包含几层子 heading，返回本次章节范围内的一组 evidence ids。 |
| `table_extraction(table_id, sql, reason)` | 需要从表格中抽取行列证据时 | 表格查询级 | 记录表格 id、SQL、命中行、evidence ids、`table_audit` 和 `query_audit`。 |
| `paragraph_extraction(element_id, pattern, reason)` | 需要从文本块中用正则定位字段片段时 | 文本匹配级 | 记录正则、匹配文本、span 和 evidence ids。 |
| `set_field(name, value, evidence_ids, reason, status, failure_reason)` | 字段证据足够或确认失败时 | 字段写入级 | 记录字段值、状态、证据 id、写入理由或失败原因。 |
| `finish()` | 所有字段都已 set_field 后 | 运行校验级 | 记录最终校验是否通过，以及缺失字段或证据错误。 |

`read_element` 和 `read_section` 的核心差异：

```text
read_element(element_id)
  -> 精确读取一个已有 HTML id
  -> trace 对应一次很小的阅读动作
  -> 适合回答“模型刚才看了哪一个块”

read_section(section_id, depth)
  -> section_id 必须是标题节点
  -> 从这个标题开始沿文件树/文档顺序递归读取其下内容
  -> 遇到同级或更高级标题停止，depth 控制子标题深度
  -> trace 对应一段章节范围，包含多个 evidence ids
  -> 适合回答“模型为了这个字段读了哪一整段上下文”
```

Public entrypoint:

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

See `docs/DESIGN.md` for the current architecture.
