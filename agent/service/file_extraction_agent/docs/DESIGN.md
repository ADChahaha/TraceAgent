# 文档问答执行设计

问答模块消费已准备的资源定位数组，执行一次模型/工具循环。资源生成由同级 `document_resources` 负责；两包互不导入，通过 storage 服务交接。资源读取归工具层，Agent 的 embedding 能力集中在 `tools/embedding.py`。

```text
resource_refs([{type, location}]) + messages + 模型/运行配置
  -> CompletionManager 调 tools/workspace.validate_resource 预检并注册 CompletionRuntime
  -> completion_runtime.stream_completion_events 包装业务事件
  -> run_qa_stream 用 resource_refs 调 open_workspace，build_tools 绑定 ToolWorkspace
  -> messages.build_qa_messages 转换历史消息
  -> loop.stream_qa_graph 调 graph.build_qa_graph，绑定 RunOptions、执行函数和停止信号
  -> QaState 保存完整 messages 与请求次数、失败信息、退避时长
  -> LangGraph agent 单次请求 / retry_wait 指数退避 / tools 工具节点
  -> loop 消费 graph.astream，转换 messages 增量、updates 模型结果和 custom 单个工具结果，输出类型化通知
  -> completion_runtime 事件字典 → CompletionRuntime 队列 → 分配 seq 并输出事件字典
  -> 传输适配层负责响应消息编码
```

## 存储访问

- 工具层通过 `service/object_store`（boto3，endpoint 指向 storage 服务，
  `S3_ENDPOINT_URL` 配置，默认 `http://localhost:9000`）读取资源。
- `open_workspace(resource_refs)` 解析资源定位数组：按 type 找到 documents 与 index 的
  `s3://<bucket>[/<key>]` 位置，GET `documents.zip` 后经 `ArchiveObjectStore` 在内存摊开
  文档树，再用 `CompositeObjectStore` 按 key 前缀把 `documents/*` 路由到归档、其余键路由到
  S3 store，最后构造 `DocumentFileTree` 与 `EmbeddingResources`。
- `DocumentFileTree` 按 key 前缀浏览/读取归档内的 `.md` 成员，越界校验仍是「key 前缀 + 拒绝
  `..`/绝对路径」；索引的 `covered_files` 校验也走同一个组合 store，因此能命中归档。
- `grep` 用纯 Python 遍历 .md 对象并做忽略大小写的字面匹配，不再依赖 ripgrep 子进程。

## 运行时与注册表

`manager.py` 只管理 CompletionManager：校验请求与资源 → 创建模型和 CompletionRuntime → 注册到 ID 映射 → 转发 stream/terminate/get_status → 运行时收尾时通过注入的 on_close 移除注册项（包括从未迭代的流）。completion_id 只保存在 manager 的注册表键和注入闭包中；清理时同时核对 ID 与运行时对象身份，避免误删其他注册项。CompletionRuntime 不接收或保存 completion_id，也不导入 manager。

`completion_runtime.py` 的内层 stream_completion_events 仅转换模型、工具和重试通知；ModelFailed 转 RuntimeError，取消异常继续传播。completion 生命周期只由外层 astream 生成。

```text
astream 创建并保存唯一对外生成器 → 首次迭代绑定事件循环并创建 producer Task
  → 输出 completion.created
  → producer 将普通事件放入 asyncio.Queue
  → consumer await queue.get，正常情况下按 FIFO 编号输出
  → Task 完成回调写内部 _DONE，唤醒 consumer（即使 Task 未进入函数体就取消）
  → 正常返回：astream 输出 completion.completed
  → 执行异常：astream 输出 completion.failed，携带 error_message
  → 主动取消：不输出终态，直接结束流
  → finally 取消并等待 producer 清理，取走 on_close 回调移除注册项
```

只保留 cancel_requested 业务标志，不保存 status、closed、terminal_committed 或独立关闭标志。
producer Task 表示执行生命周期；on_close 被取走后不会重复执行。stream 是 astream 的别名，单个运行时只允许领取一次事件生成器。调用方退出消费后 await runtime.aclose：同步 close 请求取消 → 关闭保存的事件生成器 → 由生成器 finally 等待 producer 清理并移除注册项，不递归调用 aclose。不得与同一生成器的 anext 并发调用 aclose；消费期间的外部取消使用 terminate。

业务取消调用 terminate：锁内设置取消标志，通过 call_soon_threadsafe 在事件循环取消 Task。路由 finally 只 await runtime.aclose，不自行关闭 events；同步断连回调和初始化线程仍调用 close，未启动时直接移除注册项，已启动时请求取消，由异步收尾等待清理；不再提供 disconnect。
短锁仍用于协调跨线程取消、首次启动和事件提交，不在锁内 await。取消后不再交付队列中未消费的事件，backend 自己记录取消。
manager 的 get_status 仅从取消标志推导活动请求的 in_progress/cancelling；注册项在正常终态交付前移除，之后返回 not_found。

## 执行输入与状态

QaState 继承 MessagesState，增加 model_attempt、model_failure、retry_delay_seconds。只有校验通过的完整消息进入 messages；失败尝试的部分文本不进入历史。资源路径、运行参数、工具访问器和 embedding 缓存均在图状态之外。

`run_qa_stream` 是 Agent 接口：校验非空消息和资源定位数组 → open_workspace 创建 ToolWorkspace → build_tools 绑定四个共享工具 → build_qa_messages 转换完整历史 → 调用同模块 stream_qa_graph 执行图并转换输出。loop 解析图更新，但不决定节点路由；关闭接口流时通过 aclosing 关闭内层生成器，并等待原生图流 aclose。

graph.py 绑定固定模型并编译 agent、retry_wait、tools 三个节点。agent 每次只调用一次 model_invocation；ModelCallFailure 通过 Command 更新状态，未达上限路由至 retry_wait，否则结束。retry_wait 按以 0.5 秒起步、8 秒封顶并乘 0.75–1 随机系数的指数间隔等待后回到 agent；同一逻辑模型调用总共最多五次请求。成功后计数归零，工具完成后的下一次模型调用重新计数。无效工具 ID 抛 ValueError，不发完整消息、不执行工具。

loop.stream_qa_graph 使用 graph.astream(stream_mode=["messages", "updates", "custom"])：messages 通过 LangChain 原生回调提供 chunk，updates 提供节点结束结果，custom 提供节点尚未结束时的单个 ToolMessage；loop 不重复发布 tools 的 updates。只读取 agent 节点的可见文本，过滤隐藏推理和工具参数。每次实际请求首次观察到输出时分配独立 message_id 并发送 MessageStarted，随后 MessageDelta；完成后输出带同一 ID 的完整 AIMessage。没有回调的注入模型仅在完成时输出正文，不伪装为实时生成。

失败结果保留 retry_after_seconds：从响应头优先解析 retry-after-ms，其次 Retry-After 秒数或 HTTP 日期；仅接受有限且大于 0、不超过 120 秒的值，否则回退到随机指数退避。graph 优先采用该值，不叠加抖动。等待时间只计算一次，事件使用同一值换算毫秒。

失败更新转换成 ModelRetry 或 ModelFailed。重试通知在退避结束前输出，携带失败尝试的 message_id、下一次 attempt、max_attempts=5、retry_delay_ms、error；下一次请求使用新 ID。内层将 ModelFailed 转异常，astream 根据 producer 异常生成 completion.failed。关闭图流传播取消，模型与退避中的 CancelledError 不转换为失败或重试。

RunOptions 只保留 tool_execution_timeout，默认 60 秒；删除从未参与执行的 max_tool_calls。LangGraph 的递归保护仍为 10000，由 graph 内部配置。

manager 负责输入合法性、问答模型装配和 completion 注册；资源预检委托工具层；source_indexed 只返回 result={"ok":true}，启动通知不遍历或读取文档。manager 不读取磁盘，也不持有 embedding 对象。初始化失败不注册运行时；同一活动 completion_id 不可重复。异步 gRPC 适配层通过 asyncio.to_thread 完成预检和初始化；首事件前的参数错误通过 await context.abort 映射 INVALID_ARGUMENT，其他初始化错误映射 INTERNAL。初始化与取消在锁内交接流，取消后的迟到结果在线程内关闭，停服时也不留下注册项。

route 在模块顶部直接导入 completion_manager；标准库与内部工具依赖也在顶部声明。生成端 model.py 与工具 embedding.py 分别保留 SentenceTransformer 的延迟导入，避免未使用 embedding 时加载其重依赖。

## 循环职责拆分

- loop.py：校验输入 → 初始化工具和消息 → 调用 build_qa_graph → 消费 graph.astream → 合并原生消息增量与节点更新 → 输出类型化通知并关闭图流。
- graph.py：绑定依赖 → 定义 QaState 及模型/退避/工具节点 → 配置路由与节点停止检查 → 返回编译后的图。
- contracts.py：声明模型/工具 Protocol、ModelCallAttempt、AgentOutput 和 JSON 类型。消息使用 LangChain 的具体类型；外部动态工具结果先以 object 接收，再由 messages 归一化为 JsonValue。
- messages.py：完整历史 → 系统提示与角色/工具参数转换 → 模型输入；响应 → 终止信号校验，不完整响应抛 RuntimeError。JSON 归一化供工具结果封装复用。
- model_invocation.py：固定模型与消息 → 单次 astream/ainvoke → 聚合与校验 → AIMessage 或 ModelCallFailure；finally 关闭响应流。重试由 graph 控制。
- executor.py：调用列表和工具集合 → create_task 并发 ainvoke → FIRST_COMPLETED 按共享 deadline 等待 → on_result 立即发布单项 ToolMessage → 按调用顺序返回完整历史；异常/超时转失败结果，取消时清理未完成 Task，不等待迟到线程。

## 消息批次与事件

模型配置来自既有文件/环境配置及显式请求覆盖；ConfiguredChatModel 只保存一个选定配置，API 不变、streaming=True，不再尝试其他 API 或降级 ainvoke。SDK max_retries 固定为 0，避免与图的五次尝试相乘；旧配置字段暂保留解析，但不再控制 SDK 重试。

对外模型事件为 model_message.started、model_message.delta、model_message.done，重试事件为 model_request.retrying。前端按 message_id 追加 delta；done.content 只能确认或替换，不能再次追加。重试标记旧尝试失败，新 ID 开始新正文。done 只代表本条消息完成，整轮仍以 completion 终态为准。协议是消费端行为变更，backend/前端的持久化及显示适配尚未在本次实施。


每条 gRPC 流已绑定本轮请求，所有事件均不重复携带 completion ID；事件包装入口也不接收该参数。completion_id 仅供运行时注册、取消和状态查询使用。tool_call_id 及模型 tool_calls 内的 ID 仍保留，用于调用与结果配对。

```text
模型节点调用 model_invocation._invoke_model_message
  → 校验响应完整性及工具 ID 唯一性
  → yield AIMessage
  → completion_runtime 输出 model_message.done；有调用则输出 tool_started

工具节点调用 executor._execute_tools_parallel
  → asyncio.create_task 并发执行整批工具协程
  → 按共享 deadline 和原始顺序收集成功 / 异常 / 超时结果
  → 每项 ToolMessage 携带 tool_call_id、name、additional_kwargs.tool_args、artifact、status
  → 每项完成经 on_result → graph custom → loop yield ToolMessage
  → 全部完成后才将完整结果写入图状态，供下一轮模型使用
  → completion_runtime 直接输出 tool_completed / tool_failed
```

事件包装不维护 pending 配对字典。工具节点按调用 ID 保留已发布的完整 ToolMessage；执行器异常时仅为未发布项补失败结果，再按原调用顺序写入模型历史，已发布结果不覆盖、不重复输出。普通模型调用失败在图中指数退避，五次耗尽后通过 ModelFailed 以 completion.failed 收口。

消息仅提取可见文本，不输出隐藏推理。合法 terminal stop signal 且无 tool_calls 时标记 is_final=true。图更新不重复输出历史消息或最后一条回答。

## 取消与线程边界

```text
terminate / close
  → 设置 cancel_requested，拒收新事件
  → 在所属事件循环取消 producer
  → 模型或工具 await 收到 CancelledError
  → executor finally 取消并等待未完成工具 Task
  → Task 完成回调唤醒 consumer
  → consumer 直接退出，不发 completion.cancelled
```

已经交给传输层的事件无法撤回；取消后 runtime 不再输出尚未消费的队列内容。
取消前先完成并交付的终态不会再发第二次。backend 应以自己的取消状态禁止后续写库，不依赖 agent 取消事件。
重复取消不再次中断清理。同步 to_thread 计算可能继续，迟到结果不再输出，副作用不能撤销。
模型、工具和清理协程必须协作传播取消；不保证固定清理时间。

RPC 断连回调绑定具体 runtime，避免旧 ID 误取消新请求。初始化期间取消沿用路由线程交接：迟到 runtime 调 close，未启动 producer 也可移除注册项。

## 工具与引用

工具对模型暴露 async coroutine；executor 优先 await ainvoke。文件浏览、纯 Python 搜索与本地 embedding 使用 asyncio.to_thread 执行同步叶子操作，事件循环不承担磁盘等待或推理计算。

工具各自使用单文件：`tools/ls.py`、`grep.py`、`read.py`、`embedding.py`。共享文件访问在 `workspace.py`，异常结果归一化在 `base.py`。

run_tool 只接收 execute 操作，正常返回结果，普通异常转为 ok:false。工具工厂直接使用必需的 LangChain @tool，返回 BaseTool；不保留缺依赖时退化为普通函数的分支。查询编码器使用 Embedder 协议，索引和工作区使用具体类型。

```text
workspace.validate_resource(resource_refs)
  -> 校验 documents/index 定位都存在且同 bucket
  -> embedding.load_index 校验清单版本、模型配置、向量维度/有限值和引用路径
  -> 无效资源抛 ValueError，gRPC 在首事件前返回 INVALID_ARGUMENT

search_embedding(query)
  -> 校验 query；使用工具上下文的 EmbeddingResources
  -> 从 storage 服务读取 manifest.json、index.json、vectors.npy（BytesIO 加载）
  -> 根据清单的 model_id/backend 获取缓存查询模型
  -> encode([query])，归一化查询向量并计算 top-k
  -> 返回文本、分数与文档 key 引用；工具异常转换为 ok:false
```

RPC 预检加载索引但不创建查询模型；实际工具执行时另建本轮上下文。`EmbeddingResources` 的锁保证并行查询只初始化一次索引和模型引用。查询模型按模型 ID 与后端缓存在 `embedding.py`；生成端模型缓存独立，不新增公共模型模块。问答不重建文档向量。

- `ls(path="")`：逐层浏览资源的 documents 目录。
- `grep(query, scope="", max_results=20)`：纯 Python 遍历 .md 对象并做忽略大小写的字面匹配候选行。
- `read(path)`：读取真实 Markdown 文件，拒绝文档目录之外的路径。
- `search_embedding(query, top_k=5)`：沿用资源记录的模型编码 query，从已加载索引召回文本及 covered_files；删除从未参与过滤的 scope 参数。

Markdown 文件树由资源模块创建：文档标题作为顶层目录后缀，h1–h6 按层级建目录；paragraph、list、table 分别作为文件。排序使用数字前缀；合并表格单元格展开为 Markdown。内部 index/manifest 不暴露给浏览工具。

检索只提供候选，具体事实应 read 后引用。过程消息使用可读标签链接；最终回答使用句尾数字引用，例如 `[1](documents/0001-contract/0001-section/0001-block.md)`，链接目标原样使用工具返回的 key，不汇总成末尾 Sources 区。非文档问题允许直接回答。

资源定位与工具路径是两层：RPC 的 `resource_path`（文中也称 resource_refs）保存
`s3://res_example/documents` 与 `s3://res_example/index`；工具工作区固定 bucket 后，
ls/read/grep 与检索结果使用 `documents/...` key，不传本机绝对路径或完整 S3 URL。
引用链接保存同一个 key；它不是可直接访问的 HTTP 下载地址，展示端需结合资源定位解析。
完整输入输出示例见 [工具说明](tools.md)。

## 跨轮与部署

每轮历史完全来自调用方的 append-only messages，保留 assistant tool_calls 和 tool 结果，不摘要或裁剪。资源定位数组跨轮稳定；任务与定位的关联由 backend 管理。

本次将 agent 对外传输改为 gRPC；问答仍接收资源定位数组，不接收任务 metadata。backend 尚未迁移。active completion 注册表仍是单进程内存，多个 RPC 协程共享一个 manager。

接口见 [agent API](../../../docs/API.md)，资源准备见 [资源设计](../../document_resources/docs/DESIGN.md)。
