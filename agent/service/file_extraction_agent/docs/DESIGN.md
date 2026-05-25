# File Extraction Agent Design

本文记录 `file_extraction_agent` 在 `dev-qa` 分支上的当前设计：它已经从“按 `task_spec` 抽取字段”的 agent 重构为“多文档 QA chat completion agent”。模块仍沿用历史包名，但语义已经变成 document QA：backend 每轮把 `documents + append-only messages` 传入，agent 像 code agent 浏览代码仓库一样浏览虚拟文档仓库，并通过 SSE 持续输出 `model_message`、工具事件和终态事件。

核心目标是**过程可追溯**：模型不是最后一次性给出答案和引用，而是在阅读过程中就用 Markdown evidence link 解释每个文档事实、阶段性判断和最终结论。用户可以看到模型看了哪些文档、搜了什么、读了哪些 block、什么时候把 block 展开成句子/列表项/表格行级证据，以及哪一步可能出错。

## 1. 当前边界

`file_extraction_agent` 只负责一次 QA completion 的执行，不负责上传文件、会话持久化、前端 SSE 续传或数据库写入。

```text
backend 持久化 task / messages / documents / events
  -> 每轮用户输入生成 completion_id
  -> 调用 agent POST /v1/document-qa/chat/completions
  -> agent 构建本轮 HtmlDocument virtual tree
  -> agent 运行 model/tool loop 并返回 text/event-stream
  -> backend 消费 SSE、入库、转发给前端、追加 messages
  -> agent completion 结束后释放运行时热状态
```

第一版 agent 内部只保存 active completion 的内存状态，用于当前流和取消；它不保存完整历史消息，也不把 SQLite / LangGraph checkpointer 当成会话事实来源。

## 2. 输入、输出和运行步骤

Python 入口是 `processor.create_completion_stream(...)`：

```text
completion_id + documents + messages + run_options + model_config
  -> input_adapter.build_completion_input(...)
       -> 校验 completion_id 非空
       -> 校验 documents 是非空 list，且每个 InputDocument 有 filename/html
       -> 校验 messages 是非空 list，支持 OpenAI 风格 user/assistant/tool 消息
       -> run_options 缺省补成 RunOptions(max_tool_calls=200)，并要求 max_tool_calls > 0
       -> html_index.build_html_document(documents) 构建只读语义虚拟树
  -> processor 创建 ActiveCompletion 并放入 _ACTIVE_COMPLETIONS[completion_id]
  -> model_factory.build_resolution_model(model_config) 构建 LangChain chat model
  -> processor 启动 producer 线程运行 graph.run_completion_graph_stream(...)
       -> build_graph_state(...)
       -> 输出 completion.created
       -> 输出 source_indexed(document_tree + source_selectors)
       -> resolution_new.run_resolution_stream(...)
            -> build_resolution_messages，把历史 OpenAI messages 原样转成 chat/tool messages
               并保持最新真实用户消息为最后一条 human message
            -> build_tools(state) 暴露 tree / grep / read / inspect
            -> 模型产生 model_message，先校验 provider stop signal 与 tool_calls 是否一致
            -> 有 tool_calls 时保留同轮一个或多个工具调用并交给 ToolNode 执行；terminal stop signal 且无工具时自然结束
       -> resolution 正常结束输出 completion.completed
       -> resolution 异常输出 tool_failed(resolution) + completion.failed
       -> producer 把每条 SSE event 放入 runtime queue
  -> processor 的 SSE consumer 从 runtime queue 取 event 并向 HTTP response yield
       -> 无事件时阻塞等待 runtime queue
       -> cancel endpoint 通过 runtime 往 queue 放入 cancel sentinel，主动唤醒 consumer
       -> consumer 按 FIFO 先发出 cancel sentinel 之前已提交的普通 event
       -> consumer 收到 cancel sentinel 后输出 completion.cancelled 并结束 stream，不等待 provider 下一个 chunk
       -> producer 后续若从 provider 返回更多 event，看到 runtime 已结束后丢弃
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

## 3. Cancel 和 Provider Stream 边界

当前目标设计把 agent 的 SSE 输出拆成 producer / consumer 两层，避免 cancel 被上游 provider stream 卡住：

```text
HTTP SSE consumer
  -> 阻塞等待 runtime.queue.get()
  -> 有 event 就 yield 给 backend
  -> 收到 cancel sentinel 时 close_once("cancelled")
  -> close_once 成功则 yield completion.cancelled 并关闭本轮 SSE

producer 线程
  -> 运行 graph.run_completion_graph_stream(...)
  -> graph 内部可能阻塞在 LangChain/OpenAI provider.stream()
  -> 每次 provider 请求必须使用明确 request timeout，不能无限等待
  -> provider 吐出 chunk 后继续生成 model/tool/completion event
  -> 如果 runtime 已 cancelled/closed，丢弃后续 event
```

这里的 cancel 语义是“本地 run 立刻收口”，不是保证上游 provider 物理停止生成。同步 SDK 如果卡在阻塞 IO 中，Python 不能安全强杀该调用；agent 能保证的是 `/cancel` 通过 runtime 设置取消状态并向本轮 runtime queue 投递 cancel sentinel，主动唤醒原 SSE consumer。consumer 不需要 timeout 轮询，也不等待 provider 下一个 chunk，而是把 cancel sentinel 之前已经提交到 queue 的普通 event 按 FIFO flush 给 backend，然后输出 `completion.cancelled` 并释放响应链路。

cancel 的精确边界由 runtime lock 上的提交顺序定义，而不是由用户点击取消的现实时间定义：

```text
producer commit_events([event_a, event_b]) 先拿到 runtime lock
  -> event_a/event_b 都成功进入 runtime queue，成为已提交 event
  -> cancel 后拿到 lock，只能把 cancel sentinel 排在 event_b 后面
  -> consumer 必须依次 yield event_a、event_b、completion.cancelled

cancel request_cancel() 先拿到 runtime lock
  -> cancel sentinel 进入 runtime queue
  -> runtime 进入 cancelling/closed 边界
  -> producer 后续 commit_events([...]) 发现 runtime 已取消，整批不入队
```

因此 `request_cancel()` 只阻止 cancel sentinel 之后的新 event 入队，不能丢弃 sentinel 之前已经成功提交的旧 event。producer 可以单条提交，也可以小批量提交已经在锁外生成好的 event；但提交临界区只能做状态检查和 `queue.put`，不得包含 provider stream、tool 调用、graph 运行或其他慢 IO。小批量提交的代价是 cancel 粒度变成 batch 之间；只要 batch 是很短的内存提交，就不会造成锁长期占用。

为了避免 producer/consumer 只是把卡死从前台链路挪到后台线程，provider 请求必须有有限 timeout。timeout 和重试等待采用 Ethernet binary exponential backoff 思路：同一个 completion 内最多重试五次，第 `k` 次失败后从 `[0, 2^k - 1]` 个离散 slot 中随机选择等待时长，再发起下一次 provider 调用；slot 基准时长和单次 request timeout 可由配置覆盖，但都必须是有限秒数，不能配置成无限等待。每次 provider 调用都使用明确 request timeout；如果因为 timeout 失败且还有剩余尝试，就按随机退避等待后切到下一 transport/attempt 或同 transport 重试；如果五次耗尽：

```text
runtime.cancel_requested=true
  -> producer 安静退出，consumer 已经负责输出 completion.cancelled

runtime.cancel_requested=false
  -> producer 输出 tool_failed(resolution) + completion.failed
```

因此后台 producer 最多残留到当前 provider request timeout 结束，连续 cancel 不会无限堆积僵尸线程；随机退避还能避免多个 completion 在同一时间点同时重试上游 provider。后续如果把 provider transport 改成原生 async/httpx stream，cancel 时还应主动 close socket；但即使有主动 close，有限 request timeout 和随机指数退避仍然是最后的资源回收边界。

线程安全约束：

```text
ActiveCompletion
  -> 内部持有 threading.Lock
  -> 持有本 completion 专属 runtime queue，queue 不与其他 completion 共享
  -> cancel_requested/status/closed 只能通过方法读写
  -> 状态检查、状态变更和 queue.put 必须在同一个 runtime lock 临界区里完成
  -> request_cancel() 标记取消意图，并向 runtime queue 放入 cancel sentinel 唤醒 consumer
  -> close_once(status) 原子决定唯一终态

_ACTIVE_COMPLETIONS
  -> 所有 get/set/pop 都必须持有 registry lock
  -> create_completion_stream 注册 runtime 后才能返回 SSE iterator
  -> registry 只保存 completion_id -> runtime 的索引；queue 是 runtime 私有字段，不存在全局共享 queue
  -> runtime close 后从 registry 移除

producer -> consumer event queue
  -> 如果 consumer 是 async generator，producer 线程只能通过 loop.call_soon_threadsafe(...) 投递事件
  -> 如果使用同步 StreamingResponse generator，则使用线程安全 queue.Queue
  -> 禁止 producer 线程直接操作 asyncio.Queue
  -> 已经 commit 到 queue 的普通 event 必须按 FIFO 发出，不因后续 cancel 被丢弃
  -> cancel sentinel 之后的普通 event 不允许再 commit；producer 迟到 event 直接丢弃
```

`queue.Queue` 自己的内部锁只保证队列数据结构线程安全，不保证业务上的 cancel 顺序。业务顺序必须由 `runtime.lock` 统一线性化：

```text
runtime.commit_events(events)
  -> with runtime.lock
  -> 如果 runtime 已 cancelling/closed，整批 event 不入队
  -> 否则把 events 逐个 queue.put，形成一个已提交 batch

runtime.request_cancel()
  -> with runtime.lock
  -> 如果 runtime 已 closed/cancelling，直接返回当前状态
  -> 否则设置 cancel_requested=true、status=cancelling
  -> 在同一个临界区内 queue.put(cancel sentinel)
```

不能先改 `cancel_requested` 再在锁外放 sentinel，也不能先放 sentinel 再在锁外改状态；否则 producer、consumer 看到的 runtime 状态和 queue 顺序可能不一致。consumer 可以阻塞在 `runtime.queue.get()` 上，但阻塞等待时绝不能持有 `runtime.lock`。

consumer 的结束条件来自 queue item，不直接读取 `cancel_requested`：

```text
consumer queue.get() -> 普通 event
  -> 这个 event 已经在 producer/cancel 线性化点之前成功提交
  -> consumer 直接按 FIFO yield 给 backend，不再用 cancel flag 二次裁决

consumer queue.get() -> cancel sentinel
  -> runtime.close_once("cancelled")
  -> close_once 成功才 yield completion.cancelled
  -> 结束本轮 SSE

consumer queue.get() -> completion.completed / completion.failed
  -> runtime.close_once("completed" / "failed")
  -> close_once 成功才 yield 对应终态
  -> 结束本轮 SSE
```

`cancel_requested` 只服务于入队侧：producer 用它判断后续 event 能不能 commit，cancel handler 用它避免重复塞 sentinel。consumer 如果用 `cancel_requested` 直接停流，会跳过 sentinel 前已经提交的旧 event，破坏 FIFO 语义。

终态事件只能发一次。cancel consumer、producer 正常完成和 producer 失败都会竞争调用 `runtime.close_once(status)`：

```text
consumer 收到 cancel sentinel
  -> close_once("cancelled") 成功：yield completion.cancelled 并结束 SSE
  -> close_once(...) 失败：说明 producer 已经先完成，consumer 不再发第二个终态

producer 生成 completion.completed / completion.failed / completion.cancelled
  -> close_once(status) 成功：把该 terminal event 投递给 consumer
  -> close_once(...) 失败：说明 cancel 或其他终态已经生效，丢弃该 event 并退出
```

同一个 `completion_id` 不能同时出现 `completion.cancelled`、`completion.completed` 或 `completion.failed` 中的多个终态；谁先原子关闭 runtime，谁就是唯一结果。

## 4. 虚拟文档仓库

多文档语料被映射成只读 virtual document repository，设计上模仿 code agent 看项目。每个输入 HTML 先变成一个文档目录；文档目录名会优先使用第一个 `h1` 或 `title` 作为标题后缀，但正文里的所有 `h1` 到 `h6` 都仍然会按层级生成 section 目录，不会因为第一个 `h1` 已经参与文档命名就被跳过：

```text
/
└── evidence://0001 contract-a/
    ├── evidence://0001.0001 Agreement/
    │   ├── evidence://0001.0001.0001 Termination/
    │   │   ├── evidence://0001.0001.0001.0001 Either party may terminate.md
    │   │   └── evidence://0001.0001.0001.0002 Notice period.table
    │   └── evidence://0001.0001.0002 Notices/
    │       └── evidence://0001.0001.0002.0001 Written notice must be sent.md
    └── evidence://0001.0002 Appendix/
        └── evidence://0001.0002.0001 Additional terms.md
```

建模规则：

- 根目录固定为 `/`；工具里可用 `tree(path_id="")` 或 `tree(path_id="/")` 打开。
- 每个输入 HTML 是根目录下的文档目录，文档目录的可见 locator 是 `evidence://0001`、`evidence://0002`。
- 文档标题只决定文档目录显示名；同一个 `h1` 仍会作为正文 section 目录进入树，多个 `h1` 会成为文档目录下的多个一级 section。
- `h2` 到 `h6` 按 HTML heading 层级挂到最近的更高层 section 下面。
- section header 是目录；paragraph/list/table 是可读 block 文件。
- paragraph/list/table 的可见 locator 使用稳定 `path_id`，例如 `evidence://0001.0001.0003`。
- raw virtual path 只用于内部索引；模型看到和传入工具的 locator 一律是 `evidence://...`。
- `source_selectors()` 为 document/section header 和 paragraph/list/table 生成 `path_id -> 原始 DOM id` 映射，供前端把 folder evidence 定位到 header、把 block evidence 定位到具体原文块。

## 5. 工具设计

当前只暴露四个模型工具：

```text
tree(path_id="", depth=3)
grep(query, scope="", kind="", max_results=20)
read(locator="evidence://...")
inspect(locator="evidence://...")
```

已删除旧字段抽取工具：`add_candidate_evidence`、`review_evidences`、`write_field`、`submit_result`。QA 模式不设置 `answer` 或 `finish` 工具；模型消息只有在 provider 给出 terminal stop signal（例如 `finish_reason=stop` 或 `stop_reason=end_turn`）且没有工具调用时才被视为本轮自然结束，SSE 用 `completion.completed` 收口。对应的 `model_message` 会带 `is_final=true` 和归一化后的 `stop_signal`，backend 只用这个标记决定哪条 assistant 文本进入下一轮历史。如果 provider 给出 `finish_reason=tool_calls`、`stop_reason=tool_use`、`length/max_tokens` 等非终态信号但 LangChain 消息没有实际 `tool_calls`，agent 会把该 transport 视为不完整并继续 fallback，避免把“我先去查”这类计划性文本误判为最终回答。

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

## 6. Evidence 和过程消息规则

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

多轮上下文只来自 backend 传入的 append-only `messages`：上一轮 user/assistant/tool 历史会原样保留并追加新问题。agent 不接收 memory、摘要或自动裁剪结果，避免每轮重写上下文导致 provider prompt cache 失效。新一轮如果复用旧发现，仍应引用原始 `evidence://`。

QA prompt 的默认行为不是强制查文档。模型如果能从当前对话上下文、助手身份或能力说明直接回答，就直接回答；只有用户询问文档内容、要求证据，或当前对话不足以回答时，才使用 `tree/grep/read/inspect`。一旦使用文档工具，模型需要给出简短可见的 investigation trace，说明查了什么、发现了什么、还缺什么；但不能输出隐藏推理。evidence link 只约束来自文档的事实，非文档回答不需要硬贴 evidence。

## 7. HTTP API

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
  "stream": true,
  "metadata": {"task_id": "task_001", "turn_id": "turn_003"},
  "run_options": {"max_tool_calls": 80},
  "model_config": {
    "base_url": "https://example.com/v1",
    "api_key": "...",
    "model": "...",
    "api_transport": "responses"
  }
}
```

`api_transport` 只支持 `responses` 或 `chat_completions`。每个 transport 内部仍按 stream -> invoke 做 fallback；不会在 Responses API 失败后自动切到 chat/completions。当前实现总是以 `text/event-stream` 返回流；`stream=false` 暂未实现为非流式响应。

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
  -> create_completion_stream 的 SSE consumer 被 cancel sentinel 唤醒
  -> consumer 先 flush sentinel 前已提交的普通 event，再输出 completion.cancelled 并关闭 SSE
  -> producer 若稍后从 provider 返回事件，会在 runtime 已关闭时丢弃
  -> 如果找不到 active completion，返回 status=not_found
```

示例响应：

```json
{"id": "cmp_456", "status": "cancelling"}
```

当前取消是本地 completion 级取消：不强杀进程、线程或正在进行中的同步 provider 请求，但会让 SSE consumer 不等 provider 下一个 chunk；consumer 会先按 FIFO 发出 cancel sentinel 前已经提交的普通 event，再用 `completion.cancelled` 收口。残留 producer 依赖有限 request timeout 回收，迟到事件会被丢弃。第一版必须按单进程/单 worker 部署；如果使用多个 uvicorn worker，`/cancel` 可能打到另一个进程而找不到 `_ACTIVE_COMPLETIONS` 中的 runtime。未来需要多进程或多实例时，应把 active runtime/cancel 信号移到 Redis、队列或其他外部共享运行时。

## 8. 事件模型

SSE 事件按 `seq` 递增，常见类型如下：

| 事件 | 来源 | 作用 |
| --- | --- | --- |
| `completion.created` | graph | 标记本轮 completion 开始。 |
| `source_indexed` | graph | 暴露 `document_tree` 和 `source_selectors`，backend 可提前准备 replay 高亮。 |
| `model_message` | resolution | 模型面向用户的过程说明或最终回答，事实性内容应内嵌 evidence link；最终回答带 `is_final=true` 和 `stop_signal`。 |
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
  -> 定义 InputDocument / DocumentQaMessage / DocumentQaCompletionRequest / ModelConfig / RunOptions

input_adapter.py
  -> 归一化 public input
  -> 构建 DocumentQaCompletionInput
  -> 把 documents 交给 html_index.build_html_document

impl/html_index.py
  -> 解析语义 HTML
  -> 构建 HtmlDocument、VirtualNode、path_id 索引、source_selectors、read_markdown/read_range/inline_selector_for_path

impl/html_state.py
  -> 定义 DocumentQaCompletionInput 和 GraphState
  -> 保存本轮 completion_id、HtmlDocument、messages、events、actions、next_seq

impl/html_tools.py
  -> 构建 tree / grep / read / inspect
  -> 每次工具调用写入 tool_started/tool_completed/tool_failed 事件
  -> 把内部 path_id 暴露成 evidence:// link

impl/resolution_new.py
  -> 构建 QA system prompt，并保留 backend 传入的真实 chat/tool messages
  -> 用 LangGraph 运行 model/tool loop
  -> 记录 model_message
  -> 保留 provider 返回的一个或多个 tool call，并由 ToolNode 执行

impl/graph.py
  -> 组装 completion.created/source_indexed/resolution/terminal event
  -> 把事件序列化成 SSE 字符串

processor.py
  -> 对外提供 create_completion_stream / cancel_completion / run_completion_graph_stream
  -> 管理 _ACTIVE_COMPLETIONS 内存注册表、producer/consumer 和本地 completion 级取消
```

## 9. 已删除的旧语义

本分支不再保留旧字段抽取 API 的兼容层：

- 不再接收 `task_spec`。
- 不再暴露 `POST /v1/file-extraction-agent/extract/stream`。
- 不再输出 `result_completed(fields + trace)`。
- 不再暴露 `add_candidate_evidence / review_evidences / write_field / submit_result`。
- 不再把 agent 的终态结果当成字段提交契约；多轮会话和回答持久化由 backend 负责。
