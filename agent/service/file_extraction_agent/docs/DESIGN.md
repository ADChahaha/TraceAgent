# File Extraction Agent Design

本文记录 `file_extraction_agent` 在 `dev-qa` 分支上的当前设计：它已经从“按 `task_spec` 抽取字段”的 agent 重构为“多文档 QA chat completion agent”。模块仍沿用历史包名，但语义已经变成 document QA：backend 每轮把 `documents + messages + memory` 传入，agent 像 code agent 浏览代码仓库一样浏览虚拟文档仓库，并通过 SSE 持续输出 `model_message`、工具事件和终态事件。

核心目标是**过程可追溯**：模型不是最后一次性给出答案和引用，而是在阅读过程中就用 Markdown evidence link 解释每个文档事实、阶段性判断和最终结论。用户可以看到模型看了哪些文档、搜了什么、读了哪些 block、什么时候把 block 展开成句子/列表项/表格行级证据，以及哪一步可能出错。

## 1. 当前边界

`file_extraction_agent` 只负责一次 QA completion 的执行，不负责上传文件、会话持久化、前端 SSE 续传或数据库写入。

```text
backend 持久化 task / messages / memory / documents / events
  -> 每轮用户输入生成 completion_id
  -> 调用 agent POST /v1/document-qa/chat/completions
  -> agent 构建本轮 HtmlDocument virtual tree
  -> agent 运行 model/tool loop 并返回 text/event-stream
  -> backend 消费 SSE、入库、转发给前端、更新 messages/memory
  -> agent completion 结束后释放运行时热状态
```

第一版 agent 内部只保存 active completion 的内存状态，用于当前流和取消；它不保存完整历史消息，也不把 SQLite / LangGraph checkpointer 当成会话事实来源。

## 2. 输入、输出和运行步骤

Python 入口是 `processor.create_completion_stream(...)`：

```text
completion_id + documents + messages + memory + run_options + model_config
  -> input_adapter.build_completion_input(...)
       -> 校验 completion_id 非空
       -> 校验 documents 是非空 list，且每个 InputDocument 有 filename/html
       -> 校验 messages 是非空 list，且每条 DocumentQaMessage.content 非空
       -> memory 缺省补成 DocumentQaMemory(reading_history/evidence_notes/prior_answers/open_threads)
       -> run_options 缺省补成 RunOptions(max_tool_calls=200)，并要求 max_tool_calls > 0
       -> html_index.build_html_document(documents) 构建只读语义虚拟树
  -> processor 创建 ActiveCompletion 并放入 _ACTIVE_COMPLETIONS[completion_id]
  -> model_factory.build_resolution_model(model_config) 构建 LangChain chat model
  -> graph.run_completion_graph_stream(completion_input, resolution_model)
       -> build_graph_state(...)
       -> 输出 completion.created
       -> 输出 source_indexed(document_tree + source_selectors)
       -> resolution_new.run_resolution_stream(...)
            -> build_resolution_messages，把历史 messages 和 memory 放入本轮上下文
            -> build_tools(state) 暴露 tree / grep / read / inspect
            -> 模型产生 model_message，可继续单工具循环，也可无工具结束
       -> resolution 正常结束输出 completion.completed
       -> resolution 异常输出 tool_failed(resolution) + completion.failed
  -> processor 在每个 graph event 之间检查 cancel_requested
       -> 若已取消，输出 completion.cancelled 并结束 stream
  -> finally 从 _ACTIVE_COMPLETIONS 移除本轮 completion
```

输出是 SSE 字符串迭代器，每条形如：

```text
event: model_message
data: {"seq":4,"type":"model_message","content":"..."}

```

失败时主要有两类：

- 入参校验失败：`build_completion_input` 或 Pydantic schema 抛出 `ValueError`，HTTP route 映射为 422。
- resolution 运行失败：`graph` 捕获异常，先输出 `tool_failed`，再用 `completion.failed` 收口。

## 3. 虚拟文档仓库

多文档语料被映射成只读 virtual document repository，设计上模仿 code agent 看项目：

```text
/
└── evidence://0001 contract-a/
    ├── evidence://0001.0001 Termination/
    │   ├── evidence://0001.0001.0001 Either party may terminate.md
    │   └── evidence://0001.0001.0002 Notice period.table
    └── evidence://0001.0002 Notices/
        └── evidence://0001.0002.0001 Written notice must be sent.md
```

建模规则：

- 根目录固定为 `/`；工具里可用 `tree(path_id="")` 或 `tree(path_id="/")` 打开。
- 每个输入 HTML 是根目录下的文档目录，文档目录的可见 locator 是 `evidence://0001`、`evidence://0002`。
- section header 是目录；paragraph/list/table 是可读 block 文件。
- paragraph/list/table 的可见 locator 使用稳定 `path_id`，例如 `evidence://0001.0001.0003`。
- raw virtual path 只用于内部索引；模型看到和传入工具的 locator 一律是 `evidence://...`。
- `source_selectors()` 为 document/section header 和 paragraph/list/table 生成 `path_id -> 原始 DOM id` 映射，供前端把 folder evidence 定位到 header、把 block evidence 定位到具体原文块。

## 4. 工具设计

当前只暴露四个模型工具：

```text
tree(path_id="", depth=3)
grep(query, scope="", kind="", max_results=20)
read(locator="evidence://...")
inspect(locator="evidence://...")
```

已删除旧字段抽取工具：`add_candidate_evidence`、`review_evidences`、`write_field`、`submit_result`。QA 模式不设置 `answer` 或 `finish` 工具；最后一条 assistant `model_message` 就是本轮自然结束，SSE 用 `completion.completed` 收口。

### `tree`

`tree` 展开 root、文档目录或 section 目录，用于让模型先理解多文档结构。

```text
用户问题
  -> tree(path_id="", depth=3)
  -> 模型看到文档目录、section 和 block locator
  -> 选择下一步 grep 或 read
```

`tree` 的输出可以作为结构性 evidence。例如模型说“相关内容集中在 Termination 章节”时，可以引用 section/block locator；但它不能支撑具体日期、金额或义务结论。

### `grep`

`grep` 对应 code agent 里的 `rg`，用于在 paragraph/list/table block 中找候选。

```text
grep(query="termination", scope="evidence://0001", kind="paragraph", max_results=20)
  -> 遍历 scope 下可读 block
  -> 返回 locator、kind、document、section、preview、match_spans
```

`grep` 只返回候选 block，不是最终证据。模型不能仅凭 grep preview 下具体事实结论；需要继续 `read`，必要时 `inspect`。

### `read`

`read` 打开一个 paragraph/list/table block，或读取同一 section 下连续 readable block range：

```text
read(locator="evidence://0001.0001.0003")
read(locator="evidence://range/0001.0001.0003/0001.0001.0005")
```

`read` 返回 Markdown 阅读视图。它适合理解上下文、做阶段性概括和决定是否需要精确证据。若模型要陈述具体事实、条件、例外、冲突或最终答案，应继续 `inspect`。

### `inspect`

`inspect` 把一个可读 block 展开为 inline evidence link：

```text
paragraph -> evidence://0001.0001.0003/S001
list      -> evidence://0001.0002.0001/I001
table     -> evidence://0001.0003.0001/R001
```

返回值包含：

- `locator`：被 inspect 的 block link。
- `evidence`：可直接放进 Markdown 的 inline link 列表。
- `evidence_texts`：selector 到原文片段的只读反查文本。

第一版不做 cell 级 selector；表格行级 `Rxxx` 足够支撑大多数 QA 回答，后续需要时再扩展 cell selector。

## 5. Evidence 和过程消息规则

QA 的证据主容器是 `model_message`，不是最终提交工具。只要 `model_message` 对文档做事实陈述，就应该在首次陈述时携带 Markdown evidence link。

```text
检索策略、下一步行动说明
  -> 不需要 evidence，因为它不是文档事实

文档结构、section 主题、阅读路径说明
  -> 可使用 section 或 block evidence

具体事实、日期、金额、义务、条件、例外、冲突、最终结论
  -> 应使用 inspect 产生的 Sxxx/Ixxx/Rxxx inline evidence
```

推荐输出节奏：

```text
model_message: 我先查看终止和通知相关内容，因为问题问的是能否提前终止。
工具: grep("terminate")
model_message: 命中集中在 Termination 章节，我先读该章节。[Termination](evidence://0001.0012)
工具: read("evidence://0001.0012.0003")
工具: inspect("evidence://0001.0012.0003")
model_message: 这里说明任一方可以终止协议，但该句本身没有写提前通知天数。[任一方可以终止](evidence://0001.0012.0003/S001)
```

多轮时，`memory.reading_history`、`memory.evidence_notes`、`memory.prior_answers` 和 `memory.open_threads` 可以帮助模型减少重复搜索；但上一轮总结不能替代原文 evidence。新一轮如果复用旧发现，仍应引用原始 `evidence://`。

## 6. HTTP API

当前 route 暴露：

```text
POST /v1/document-qa/chat/completions
GET  /v1/document-qa/chat/completions/{completion_id}
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

### 创建 completion

请求体：

```json
{
  "completion_id": "cmp_456",
  "documents": [
    {"filename": "contract.pdf", "html": "<h1>Agreement</h1><p>...</p>"}
  ],
  "messages": [
    {"role": "user", "content": "这份合同可以提前终止吗？"}
  ],
  "memory": {
    "reading_history": [],
    "evidence_notes": [],
    "prior_answers": [],
    "open_threads": []
  },
  "stream": true,
  "metadata": {"task_id": "task_001", "turn_id": "turn_003"},
  "run_options": {"max_tool_calls": 80},
  "model_config": {
    "base_url": "https://example.com/v1",
    "api_key": "...",
    "resolution_model_name": "..."
  }
}
```

当前实现总是以 `text/event-stream` 返回流；`stream=false` 暂未实现为非流式响应。

### 查询 completion

`GET /v1/document-qa/chat/completions/{completion_id}` 当前是占位调试入口，返回：

```json
{"status": "not_implemented"}
```

如果后续需要查询 active runtime 状态，应在不引入持久 conversation 的前提下扩展这里。

### 取消 completion

```text
POST /v1/document-qa/chat/completions/{completion_id}/cancel
  -> processor.cancel_completion(completion_id)
  -> 如果 completion 在 _ACTIVE_COMPLETIONS 中，设置 cancel_requested=true、status=cancelling
  -> create_completion_stream 在下一个 graph event 边界输出 completion.cancelled 并关闭 SSE
  -> 如果找不到 active completion，返回 status=not_found
```

示例响应：

```json
{"id": "cmp_456", "status": "cancelling"}
```

当前取消是 cooperative cancellation，不强杀进程、线程或正在进行中的模型请求。第一版必须按单进程/单 worker 部署；如果使用多个 uvicorn worker，`/cancel` 可能打到另一个进程而找不到 `_ACTIVE_COMPLETIONS` 中的 runtime。未来需要多进程或多实例时，应把 active runtime/cancel 信号移到 Redis、队列或其他外部共享运行时。

## 7. 事件模型

SSE 事件按 `seq` 递增，常见类型如下：

| 事件 | 来源 | 作用 |
| --- | --- | --- |
| `completion.created` | graph | 标记本轮 completion 开始。 |
| `source_indexed` | graph | 暴露 `document_tree` 和 `source_selectors`，backend 可提前准备 replay 高亮。 |
| `model_message` | resolution | 模型面向用户的过程说明或最终回答，事实性内容应内嵌 evidence link。 |
| `tool_started` | html_tools | 记录工具开始及参数。 |
| `tool_completed` | html_tools | 记录工具成功结果。 |
| `tool_failed` | html_tools / graph | 记录工具或 resolution 失败。 |
| `completion.completed` | graph | 正常结束。 |
| `completion.cancelled` | processor | 后端请求取消后结束。 |
| `completion.failed` | graph | resolution 失败后结束。 |

backend 应把这些事件作为事实流持久化；前端断线续传和历史回放应读取 backend 数据库，而不是依赖 agent 仍保留 runtime。

## 8. 模块职责

```text
schemas.py
  -> 定义 InputDocument / DocumentQaMessage / DocumentQaMemory / DocumentQaCompletionRequest / ModelConfig / RunOptions

input_adapter.py
  -> 归一化 public input
  -> 构建 DocumentQaCompletionInput
  -> 把 documents 交给 html_index.build_html_document

impl/html_index.py
  -> 解析语义 HTML
  -> 构建 HtmlDocument、VirtualNode、path_id 索引、source_selectors、read_markdown/read_range/inline_selector_for_path

impl/html_state.py
  -> 定义 DocumentQaCompletionInput 和 GraphState
  -> 保存本轮 completion_id、HtmlDocument、messages、memory、events、actions、next_seq

impl/html_tools.py
  -> 构建 tree / grep / read / inspect
  -> 每次工具调用写入 tool_started/tool_completed/tool_failed 事件
  -> 把内部 path_id 暴露成 evidence:// link

impl/resolution_new.py
  -> 构建 QA system prompt 和本轮 HumanMessage
  -> 用 LangGraph 运行 model/tool loop
  -> 记录 model_message
  -> 请求 provider 禁用 parallel tool calls；如果仍返回多个 tool call，只保留第一个

impl/graph.py
  -> 组装 completion.created/source_indexed/resolution/terminal event
  -> 把事件序列化成 SSE 字符串

processor.py
  -> 对外提供 create_completion_stream / cancel_completion / run_completion_graph_stream
  -> 管理 _ACTIVE_COMPLETIONS 内存注册表和 cooperative cancellation
```

## 9. 已删除的旧语义

本分支不再保留旧字段抽取 API 的兼容层：

- 不再接收 `task_spec`。
- 不再暴露 `POST /v1/file-extraction-agent/extract/stream`。
- 不再输出 `result_completed(fields + trace)`。
- 不再暴露 `add_candidate_evidence / review_evidences / write_field / submit_result`。
- 不再把 agent 的终态结果当成字段提交契约；多轮会话和回答持久化由 backend 负责。
