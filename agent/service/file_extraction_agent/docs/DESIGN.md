# File Extraction Agent Design

本文记录 `file_extraction_agent` 在 `dev-qa` 分支上的当前设计：它已经从“按 `task_spec` 抽取字段”的 agent 重构为“多文档 QA chat completion agent”。模块仍沿用历史包名，但语义已经变成 document QA：backend 每轮把 `documents + append-only messages` 传入，agent 把 HTML 落成真实文件树，像 code agent 浏览代码仓库一样浏览它，并通过 SSE 持续输出 `model_message`、工具事件和终态事件。

核心目标是**过程可追溯**：模型会在阅读过程中用真实文件路径的 Markdown evidence link 解释每个文档事实和阶段性判断；最终回答像 NotebookLM 一样把数字 evidence citation 紧跟在被支撑的句子后面。用户可以看到模型看了哪些文档、搜了什么、读了哪些 block 文件，以及每个最终结论句引用了哪些来源。

**技术定位：Agentic RAG（工具式检索 + 可选的语义候选召回）。** 模型用 `ls / grep / read` 三个工具在真实文件树上按需检索（`grep` 走 ripgrep，是词法/稀疏检索），并可用第 4 个工具 `search_embedding` 做语义候选召回：它把当前文档按固定 token 窗口 + overlap 切 chunk（chunk 可在文档内跨多个 `.md` 块），对 chunk 与 query 做 embedding 余弦检索，返回带 `text` / `document` / `covered_files` 的候选 chunk。语义召回是词法检索的**补充**，不是替代——`search_embedding` 与 `grep` 一样只给候选，模型仍需 `read` 被覆盖的文件核对后才可引证，因此保留了证据可解释性。

## 1. 当前边界

`file_extraction_agent` 只负责一次 QA completion 的执行，不负责上传文件、会话持久化、前端 SSE 续传或数据库写入。

```text
backend 持久化 task / messages / documents / events
  -> 每轮用户输入生成 completion_id
  -> 调用 agent POST /v1/document-qa/chat/completions
  -> agent 把 documents 落盘成真实文件树并运行 model/tool loop 返回 text/event-stream
  -> backend 消费 SSE、入库、转发给前端、追加 messages
  -> agent completion 结束后清理本轮 workspace 并释放运行时热状态
```

第一版 agent 内部只保存 active completion 的内存状态，用于当前流和取消；它不保存完整历史消息，也不把 SQLite / LangGraph checkpointer 当成会话事实来源。

**检索现状与演进**：当前检索是"工具式、词法级"（`grep`/ripgrep）为主，另增 `search_embedding` 作为**语义候选召回**补充（固定窗口分块 + 余弦检索 + 返回 chunk 文本与覆盖的 `.md` 块）。词法检索轻量可解释；`search_embedding` 覆盖"问句用词与文档用词不同"的语义改写召回。索引按内容哈希键持久化到磁盘复用，文档变更时自动失效。embedding 模型默认 `bekko-embedding-v1-a8m`（OpenVINO 后端），模型、分块窗口、索引目录均可用环境变量覆盖。

配套草稿文档：

- [flowchart.md](flowchart.md)：描述 chat completions、cancel 和 agent loop 的高层流程。
- [agent_loop.md](agent_loop.md)：描述更轻量的协作式 cancel 伪代码；在 backend 作为事实来源时，agent 只需要在安全点检查 `cancel_flag` 并尽快停止。
- [tools.md](tools.md)：描述 `ls / grep / read` 三个工具的表面。

## 2. 消息执行与事件包装边界

`loop` 只执行并返回消息；`manager` 把消息转成业务事件；`ActiveCompletion.stream` 最后编码 SSE。

```text
completion_id + documents + messages + run_options + model_config
  -> CompletionManager.create / prepare_completion_state
     校验安全 completion_id、非空文件名/HTML/消息，独占创建 workspace
     materialize_tree 将 HTML 落成 DocumentFileTree，构造 GraphState
  -> build_resolution_model 构造支持 bind_tools 的模型；失败则清理 workspace
  -> 注册 ActiveCompletion，首次消费 stream 时启动 producer
  -> run_completion_graph_stream 先输出 completion.created / source_indexed
  -> run_resolution_stream 构建 system prompt、历史消息和 tools
     -> LangGraph stream(mode="updates") 取每个节点的 messages
     -> 原样 yield AIMessage 或 ToolMessage，不包装 ok/output 或写事件列表
  -> manager 按消息类型组装事件字典
     -> AIMessage：model_message；有 tool_calls 则追加对应 tool_started
     -> ToolMessage：按 tool_call_id 找回名称/参数，包装 tool_completed/tool_failed
  -> runtime 锁内提交事件字典到 queue.Queue
  -> consumer 按 FIFO 取事件、分配递增 seq、统一 _sse 编码后交给 backend
  -> 正常结束 completion.completed；异常 completion.failed；取消 completion.cancelled
  -> finally 清理 workspace、从注册表移除 completion
```

`GraphState` 只保存 completion_id、文档树、输入消息、运行配置、task_id 和工作目录归属；不保存 events、actions、next_seq、current_model_content、failed_stage、events_lock 或 tool_batch_active。LangGraph 自己维护本轮消息历史，manager 不通过共享 state 读取消息副作用。

工具只返回结果：`run_tool` 捕获普通异常并转为 `{ok:false, errors:[...]}`；并行执行器使用共享 deadline，按调用顺序生成带原始 call ID 的 ToolMessage。结果放在消息的 content；原始结果保存在 ToolMessage.artifact 供 manager 无损包装，status 表示成功/失败。线程超时后不再读取迟到结果，线程也没有事件/action 写入渠道。

manager 用本轮局部 pending 字典按 tool_call_id 保存未完成调用；收到 ToolMessage 后移除对应项。同名并行调用分别配对。tool_started 表示收到调用并开始调度，不表示每个工作线程的精确启动时刻。消息内容块只提取可见文本，模型事件不暴露隐藏推理；最终回答仍通过合法 stop signal 和无 tool_calls 标记 is_final。

模型请求失败或响应不完整由 loop 的调用尝试处理，全部耗尽抛 RuntimeError；manager 补齐尚未配对的失败结果，输出 tool_failed(resolution) 后收口。工具异常/超时通常作为 ToolMessage 返回模型，允许继续作答；未知消息类型或未配对结果按协议错误结束。图自然结束时不额外 yield 重复的最后一条消息。

输入及缓存边界保持不变：metadata.task_id 由 route 传到 GraphState；embedding 缓存按任务、文档内容和相对路径、模型及分块配置生成版本键。缓存中的相对路径映射到本轮 workspace。危险 completion_id、已有目录或越界清理抛 ValueError；HTML 表格展开合并单元格后输出 Markdown。

## 3. 取消、终态与线程边界

执行层不读取消标志。manager 在继续请求下一条消息前检查取消；已经发布工具调用时，先消费其全部 ToolMessage，再停止，不请求下一轮模型。

```text
ActiveCompletion.commit_event(model_message with tool_calls)
  -> 同一个 runtime 锁内标记活动批次并提交模型事件
  -> 后续 tool_started 和结果事件保持 FIFO
  -> 已发布调用都返回结果后清除活动批次

terminate()
  -> 同一个 runtime 锁内设置 cancel_requested
  -> 无活动批次：放 cancel sentinel，唤醒 consumer
  -> 有活动批次：标记 deferred cancel，让结果（含超时失败）先提交
  -> manager 在批次完成后输出 completion.cancelled
```

取消早于模型事件提交时，该迟到消息不再发布；取消晚于模型事件提交时，已发布的工具调用必须配齐结果。若批次中执行流抛异常，manager 按 pending call ID 补失败回复；取消优先以 cancelled 收口。事件转换器关闭时也关闭内层消息生成器，避免继续请求 provider。

producer 通过 runtime 锁控制事件提交；consumer 的结束条件是队列中的终态或 sentinel，不用取消标志跳过已提交事件。terminal_committed 防止终态重复入队，close_once 防止重复关闭；consumer 统一为普通事件和各种终态分配 seq，图内不分配序号。

queue.get 阻塞时不持有 runtime 锁。没有活动工具批次的取消不等待 provider 下一个 chunk；同步 provider 及已超时工具线程不能被强杀，有限请求 timeout 负责约束阻塞时间，迟到结果不能再写事件。注册表仅在进程内共享，部署仍要求单进程/单 worker。

## 4. 真实文件树

多文档语料被落盘成一个真实文件 tree，模型像 code agent 看项目一样浏览。
每个输入 HTML 先变成一个文档目录；文档目录名会优先使用第一个 `h1` 或
`title` 作为标题后缀，但正文里的所有 `h1` 到 `h6` 都仍然会按层级生成
section 目录，不会因为第一个 `h1` 已经参与文档命名就被跳过：

```text
/tmp/qa_workspace/<completion_id>/
    └── 0001-contract-Agreement/
        └── 0001-Agreement/
            ├── 0001-Termination/
            │   ├── 0001-Either party may terminate.md
            │   └── 0002-Notice period.md
            └── 0002-Notices/
                └── 0001-Written notice must be sent.md
```

建模规则：

- 每个输入 HTML 是 workspace 根目录下的文档目录，目录名数字前缀按文档顺序递增。
- 文档标题只决定文档目录显示名；同一个 `h1` 仍会作为正文 section 目录进入树，
  多个 `h1` 会成为文档目录下的多个一级 section。
- `h2` 到 `h6` 按 HTML heading 层级挂到最近的更高层 section 下面。
- section header 是目录；paragraph/list/table 是 `.md` 文件（列表和表格整表一个文件）。
- 目录 / 文件排序靠数字前缀（`0001-` / `0002-`），不靠 `os.listdir`。
- 没有 `path_id` / `evidence://`；模型看到和引用的都是真实 `.md` 文件路径。
- `source_indexed` 事件暴露 `workspace_root` 和逐层 `tree` 清单。

## 5. 工具设计

当前暴露四个模型工具：

```text
ls(path="")
grep(query, scope="", max_results=20)
read(path="/abs/.../0001-section/0001-block.md")
search_embedding(query, top_k=5, scope="")
```

已删除旧字段抽取工具：`add_candidate_evidence`、`review_evidences`、
`write_field`、`submit_result`。也删除了旧的 `inspect`、`evidence://` /
`path_id` locator 和 `evidence://range` 连续读取。QA 模式不设置 `answer` 或
`finish` 工具；模型消息只有在 provider 给出 terminal stop signal（例如
`finish_reason=stop` 或 `stop_reason=end_turn`）且没有工具调用时才被视为本轮
自然结束，SSE 用 `completion.completed` 收口。对应的 `model_message` 会带
`is_final=true` 和归一化后的 `stop_signal`，backend 只用这个标记决定哪条
assistant 文本进入下一轮历史。如果 provider 给出 `finish_reason=tool_calls`、
`stop_reason=tool_use`、`length/max_tokens` 等非终态信号但 LangChain 消息没有
实际 `tool_calls`，agent 会把该 transport 视为不完整并继续 fallback。

### `ls`

`ls` 列出 workspace 根、文档目录或 section 目录的当前一层，用于让模型逐层
理解多文档结构，避免一次工具调用把深层目录全部塞进上下文。

```text
用户问题
  -> ls(path="")
  -> 模型看到文档目录路径
  -> ls(path="/tmp/qa_workspace/<cid>/0001-contract")
  -> 模型看到该文档当前层的 section 或 .md 文件路径
  -> 选择下一步 grep、read 或继续 ls 子 section
```

`ls` 的输出可以作为结构性 evidence，但不能支撑具体日期、金额或义务结论。

### `grep`

`grep` 对应 code agent 里的 `rg`，用于在全部 `.md` block 中找候选。

```text
grep(query="termination", scope="/tmp/.../0001-contract/0001-Termination", max_results=20)
  -> 在 scope 目录跑 rg 子进程，stdout 原样返回（带文件路径 + 行号 + 匹配行）
  -> 不限定 scope 时在整个 workspace 根目录搜索
```

`grep` 只返回候选行，不是最终证据。模型需要继续 `read` 具体文件确认。

### `search_embedding`

`search_embedding` 是语义候选召回工具，用于 grep 命中不足或"问句用词与文档用词不同"的场景。它把当前 workspace 的每个文档（按文件树顺序拼接其全部 `.md` 块文本）切成固定 token 窗口 + overlap 的 chunk（chunk 可在文档内横跨多个 `.md` 块），再对 query 与各 chunk 做 embedding 余弦检索：

```text
search_embedding(query="early termination", top_k=5, scope="")
  -> embedder.encode([query])                              # 惰性单例，OpenVINO/torch
  -> index = _get_index(state, embedder)                    # task_id + 文档版本磁盘缓存 -> 未命中则构建落盘
  -> search_top_k(query_vec, index, top_k)                  # 纯 numpy 余弦
  -> 返回 [{score, document, chunk_id, text, token_range, covered_files}]
```

返回的每个候选 chunk 带：

- `text`：chunk 原文，模型可直接用于理解与作答，无需额外 `read`。
- `document`：chunk 归属的源文档名（文件树目录名），用于跨文档追踪。
- `covered_files`：该 chunk 覆盖到的所有 `.md` 块绝对路径。chunk 在文档内跨块切分，因此可能列出多个 `.md` 文件；模型引证时引用其中任一真实路径即可。

与 `grep` 一致，`search_embedding` 只返回候选 chunk，**不是最终证据**；模型应 `read` 被覆盖的文件核对后再引证，以保留证据可解释性。索引按内容哈希键持久化到磁盘复用，文档变更时自动失效重建。

### `read`

`read` 打开一个 `.md` block 文件，返回其 markdown 内容：

```text
read(path="/tmp/qa_workspace/<cid>/0001-contract/0001-Termination/0001-Either party may terminate.md")
  -> open().read() 返回该段落的 markdown 文本
```

`read` 返回 Markdown 阅读视图。段落返回纯文本，列表返回 bullet，表格返回
markdown 表格（整表一个文件）。模型用它理解上下文、做阶段性概括，并据此
引用文件路径作为证据。

## 6. Evidence 和过程消息规则

QA 的证据主容器是 `model_message`，不是最终提交工具。过程 `model_message` 对文档做事实陈述时，应在首次陈述时携带带可读 label 的 Markdown evidence link；最终 `model_message` 用 `is_final=true` 标记，并把数字 label 的 evidence citation 紧跟在被支撑的句子后面，不再收束成末尾 `Sources` 区。

```text
检索策略、下一步行动说明
  -> 不需要 evidence，因为它不是文档事实

文档结构、section 主题、阅读路径说明
  -> 可使用 section 或 block 文件路径

过程中的具体事实、日期、金额、义务、条件、例外、冲突
  -> 应引用被 read 的 .md 文件路径

最终回答正文里的文档事实
  -> 正文先写结论和说明，再把 [1](/abs/path/...md) 这类数字 citation 紧跟在对应句子后面
```

推荐输出节奏：

```text
model_message: 我先查看终止和通知相关内容，因为问题问的是能否提前终止。
工具: grep("terminate")
model_message: 命中集中在 Termination 章节，我先读该章节。[Termination](/abs/0001-contract/0001-Termination)
工具: read("/abs/0001-contract/0001-Termination/0001-termination.md")
model_message: 这里说明任一方可以终止协议，但该句本身没有写提前通知天数。[任一方可以终止](/abs/0001-contract/0001-Termination/0001-termination.md)
model_message(is_final=true): 可以提前终止。[1](/abs/0001-contract/0001-Termination/0001-termination.md) 还需要满足书面通知要求。[2](/abs/0001-contract/0001-Notices/0001-notices.md)
```

多轮上下文只来自 backend 传入的 append-only `messages`：上一轮 user/assistant/tool 历史会原样保留并追加新问题。agent 不接收 memory、摘要或自动裁剪结果，避免每轮重写上下文导致 provider prompt cache 失效。新一轮如果复用旧发现，仍应引用原始 `.md` 文件路径。

QA prompt 的默认行为不是强制查文档。模型如果能从当前对话上下文、助手身份或能力说明直接回答，就直接回答；只有用户询问文档内容、要求证据，或当前对话不足以回答时，才使用 `ls/grep/read`。一旦使用文档工具，模型需要给出简短可见的 investigation trace，说明查了什么、发现了什么、还缺什么；但不能输出隐藏推理。evidence link 只约束来自文档的事实，非文档回答不需要硬贴 evidence。过程消息使用可读 citation label；最终回答使用 `[1](/abs/path/...md)`、`[2](/abs/path/...md)` 这类数字 label，并把数字 citation 放在被支撑句子后面，不收束成一个总 `Sources` 区。

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
  -> completion_manager.terminate(completion_id)
  -> 如果 completion 在 CompletionManager 注册表中，设置 cancel_requested=true、status=cancelling
  -> completion_manager.create 的 SSE consumer 被 cancel sentinel 唤醒
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
| `completion.created` | manager | 标记本轮 completion 开始。 |
| `source_indexed` | manager | 暴露本轮 `workspace_root` 和逐层 `tree` 清单。 |
| `model_message` | manager | 模型面向用户的过程说明或最终回答；过程事实应内嵌带可读 label 的 evidence link，最终回答带 `is_final=true` 和 `stop_signal`，并把数字 evidence citation 放在被支撑句子后面。 |
| `tool_started` | manager | 记录工具开始及参数。 |
| `tool_completed` | manager | 记录工具成功结果。 |
| `tool_failed` | manager | 记录工具或 resolution 失败。 |
| `completion.completed` | manager | 正常结束。 |
| `completion.cancelled` | manager | 后端请求取消后结束。 |
| `completion.failed` | manager | resolution 失败后结束。 |

backend 应把这些事件作为事实流持久化；前端断线续传和历史回放应读取 backend 数据库，而不是依赖 agent 仍保留 runtime。

## 8. 模块职责

```text
schemas.py
  -> 定义 InputDocument / DocumentQaMessage / DocumentQaCompletionRequest / ModelConfig / RunOptions

core/documents.py
  -> 解析语义 HTML
  -> 构建 DocumentFileTree（真实目录 + .md 文件）
  -> 提供 entries / read / scope_path；不再有 path_id / source_selectors / 句行级 selector
  -> 分块输入由 core/tools/embedding/index.py 的 _build_streams/_md_files_under 收集

core/graph.py
  -> 定义 GraphState 与 build_graph_state（输入与文档执行上下文，无事件缓冲）
  -> 不做事件组装与 SSE 写出；manager.run_completion_graph_stream 组装事件字典，
     ActiveCompletion.stream 负责运行时收口及 SSE 输出

core/tools/              # 工具包：每个工具一个文件，统一由 __init__ 暴露 build_tools
  -> __init__.py 对外统一接口 build_tools(state)，转出 _ls/_grep/_read/_search_embedding
     及可替身点 _run_ripgrep/_get_embedder/_get_index（供测试 monkeypatch）
  -> base.py    共享骨架：run_tool 只执行并归一化异常结果；expose_entries / order_key
  -> ls.py      构建 ls 工具 + _ls / _ls_result
  -> grep.py    构建 grep 工具 + _grep / _grep_output / _run_ripgrep（rg 子进程，引用证据用真实 .md 路径）
  -> read.py    构建 read 工具 + _read / _read_result / _locator_error
  -> embedding/  embedding 能力内聚子包（承载 search_embedding 工具）
      __init__.py  search_embedding 工具（glue）+ _search_embedding / _get_embedder + 转出常量
      model.py    真实模型惰性封装：get_embedder / get_tokenizer（不在 import 时加载 torch/OpenVINO）
      search.py   纯 numpy 分块/索引/余弦检索：chunk_text / build_index / search_top_k
      index.py    索引持久化 + 内容哈希缓存 key + _build_streams 收集文档流 + _get_index
  core/tools 只返回工具结果，manager 将 ToolMessage 包装成事件；
  search_embedding 用纯 numpy 余弦返回候选 chunk（含 text/document/covered_files）

core/loop.py
  -> 构建 QA system prompt，并保留 backend 传入的真实 chat/tool messages
  -> 用 LangGraph 运行 model/tool loop
  -> 原样 yield AIMessage / ToolMessage，由 manager 包装事件
  -> 保留 provider 返回的一个或多个 tool call，并交给 _execute_tools_parallel 并行执行
     （整批共享 tool_execution_timeout 期限，返回顺序稳定，无共享事件写入）

core/model.py
  -> build_resolution_model / normalize_model_config / build_chat_model
  -> 产出 ChatModelFallbackChain（按 transport 排 stream -> invoke 两级 attempt）

manager.py
  -> prepare_completion_state(...) 做入口校验（非空、filename/html 非空）、
     派生 workspace_root、触发 materialize_tree 落盘并产出 GraphState（失败抛 ValueError）
  -> run_completion_graph_stream(...)：把一轮 completion 的事件（completion.created /
     source_indexed / resolution / terminal）组装成事件字典，并在结尾按终止类型选终态；
     接受可选的 should_stop 回调，用于在每一步间检查外部取消信号
  -> ActiveCompletion：单 completion 的运行时，持有 state + resolution_model + 专属 queue + 锁；
     stream()（起 producer 线程 + 消费队列产 SSE + finally 清理）、_produce()（跑
     run_completion_graph_stream 并注入 should_stop=lambda: self.cancel_requested 投事件）、
     terminate()/get_status()；事件通道与终态由锁线性化
  -> CompletionManager：多 completion 的注册表 + create 装配（state+model -> ActiveCompletion -> 注册 ->
     返回 stream）+ terminate/status 转发 + _managed_stream 收尾移除注册表
  -> 进程内单例 completion_manager 是公开入口，HTTP 路由直接 completion_manager.create(...) /
     completion_manager.terminate(...)
```

## 9. 已删除的旧语义

本分支不再保留旧字段抽取 API 的兼容层：

- 不再接收 `task_spec`。
- 不再暴露 `POST /v1/file-extraction-agent/extract/stream`。
- 不再输出 `result_completed(fields + trace)`。
- 不再暴露 `add_candidate_evidence / review_evidences / write_field / submit_result`。
- 不再把 agent 的终态结果当成字段提交契约；多轮会话和回答持久化由 backend 负责。
