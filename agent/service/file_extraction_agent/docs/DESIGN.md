# 文档问答执行设计

问答模块消费已准备的资源路径，执行一次模型/工具循环。资源生成由同级 `document_resources` 负责；两包互不导入，通过磁盘文件格式交接。资源读取归工具层，Agent 的 embedding 能力集中在 `tools/embedding.py`。

```text
resource_path + messages + 模型/运行配置
  → CompletionManager 调 tools/workspace.validate_resource 预检并注册 CompletionRuntime
  → completion_runtime.stream_completion_events 包装业务事件
  → run_qa_stream 用 resource_path 调 open_workspace，build_tools 绑定 ToolWorkspace
  → messages.build_qa_messages 转换历史消息
  → graph.build_qa_graph 绑定 RunOptions、模型/工具执行函数与节点路由
  → 仅 messages 进入 LangGraph
  → LangGraph 模型节点 / 工具节点
  → AIMessage / list[ToolMessage]
  → completion_runtime 事件字典 → CompletionRuntime 队列 → 分配 seq 并编码 SSE
```

## 运行时与注册表

`manager.py` 只管理 CompletionManager：校验请求与资源 → 创建模型和 CompletionRuntime → 注册到 ID 映射 → 转发 stream/terminate/get_status → 在流 finally 中移除注册项。completion_id 只保存在 manager 的注册表键和流清理闭包中；清理时同时核对 ID 与运行时对象身份，避免误删其他注册项。

`completion_runtime.py` 管理单轮 CompletionRuntime，以及 stream_completion_events、事件转换和 SSE 编码：后台 producer 执行 loop → 提交业务事件到锁保护的队列 → consumer 按 FIFO 编号输出 → 完成/失败/取消时唯一收尾。它不接收或保存 completion_id，不导入 manager，也不维护全局注册表。后台线程使用固定名称 qa-completion，名称只用于调试。

## 执行输入与状态

图内只使用 LangGraph MessagesState 保存消息，不再定义自有 GraphState。资源路径、运行参数、工具访问器和 embedding 缓存均在图状态之外。

`run_qa_stream` 校验非空消息和资源路径，然后调用 open_workspace(resource_path) 创建 ToolWorkspace；build_tools(workspace) 让四个工具闭包共享文档访问器和 EmbeddingResources。build_qa_messages(messages) 转换完整历史；build_qa_graph(model, tools, run_options) 将工具超时绑定到执行闭包。建图逻辑独立放在 core/graph.py，包括 agent/tools 节点、条件路由与 compile；loop.py 从 model_invocation.py 与 executor.py 注入 invoke_model/execute_tools 两个执行函数并消费图更新，graph.py 不反向导入 loop.py。执行器只接收工具调用、工具集合和 timeout。无效输入抛 ValueError；工具失败与取消仍遵守原批次契约。

manager 负责输入合法性、问答模型装配和 completion 注册；资源预检委托工具层；source_indexed 只返回 result={"ok":true}，启动通知不遍历或读取文档。manager 不读取磁盘，也不持有 embedding 对象。初始化失败不注册运行时；同一活动 completion_id 不可重复。HTTP route 在线程池中完成预检，避免阻塞异步事件循环。

route 在模块顶部直接导入 completion_manager；标准库与内部工具依赖也在顶部声明。生成端 model.py 与工具 embedding.py 分别保留 SentenceTransformer 的延迟导入，避免未使用 embedding 时加载其重依赖。

## 循环职责拆分

- loop.py：校验输入 → 初始化工具和消息 → 建图 → 消费 updates → 转发 AIMessage/完整工具批次 → 检查取消 → finally 关闭图流。
- messages.py：完整历史 → 系统提示与角色/工具参数转换 → 模型输入；响应 → 终止信号校验，不完整响应抛 RuntimeError。JSON 归一化供工具结果封装复用。
- model_invocation.py：模型与消息 → stream/invoke 尝试 → 聚合消息 → messages 校验 → 成功返回；失败随机退避，最多五次，耗尽后抛 RuntimeError。
- executor.py：调用列表和工具集合 → 并行执行 → 共享 deadline 收集 → 按原顺序封装 ToolMessage；异常/超时转失败结果，不等待迟到线程。

## 消息批次与事件

每条 SSE 流已绑定本轮请求，所有 SSE 事件均不重复携带 completion ID；事件包装入口也不接收该参数。completion_id 仅供运行时注册、取消和状态查询使用。tool_call_id 及模型 tool_calls 内的 ID 仍保留，用于调用与结果配对。

```text
模型节点调用 model_invocation._invoke_model_message
  → 校验响应完整性及工具 ID 唯一性
  → yield AIMessage
  → completion_runtime 输出 model_message；有调用则输出 tool_started

工具节点调用 executor._execute_tools_parallel
  → ThreadPoolExecutor 并行执行整批调用
  → 按共享 deadline 和原始顺序收集成功 / 异常 / 超时结果
  → 每项 ToolMessage 携带 tool_call_id、name、additional_kwargs.tool_args、artifact、status
  → 整批 yield list[ToolMessage]
  → completion_runtime 直接输出 tool_completed / tool_failed
```

事件包装不维护 pending 配对字典。执行器整体异常也由工具节点转换成整批失败结果，允许模型继续说明失败；普通模型调用失败在尝试耗尽后向 completion_runtime 抛 RuntimeError，以 completion.failed 收口。

消息仅提取可见文本，不输出隐藏推理。合法 terminal stop signal 且无 tool_calls 时标记 is_final=true。图更新不重复输出历史消息或最后一条回答。

## 取消与线程边界

```text
发布带 tool_calls 的模型事件
  → runtime 锁内登记活动调用 ID 并入队
  → terminate 在同一锁内设置取消标志
     ├─ 无活动批次：入队取消 sentinel，立即唤醒 consumer
     └─ 有活动批次：延迟取消，让该批次结果先提交
  → loop 在整批结果 yield 后检查 should_stop，不再调用下一轮模型
  → CompletionRuntime 输出 completion.cancelled
```

CompletionRuntime 的调用 ID 集合只用于取消时判断批次是否结清，不保存调用参数、不承担消息配对。consumer 按 FIFO 输出已提交事件，终态与 close 均唯一；取消后的迟到模型事件会被拒收。

关闭事件流时关闭内层生成器。同步 provider 和工具线程不能强杀；请求 timeout 和工具 deadline 约束阻塞，超时线程的迟到结果不会再写事件。问答结束只释放运行时，不删除资源。

## 工具与引用

工具各自使用单文件：`tools/ls.py`、`grep.py`、`read.py`、`embedding.py`。共享文件访问在 `workspace.py`，异常结果归一化在 `base.py`。

```text
workspace.validate_resource(resource_path)
  → 校验受管理绝对路径、documents 目录及内部链接
  → embedding.load_index 校验清单版本、模型配置、向量维度/有限值和引用路径
  → 无效资源抛 ValueError，HTTP 在 SSE 开始前返回 422

search_embedding(query)
  → 校验 query；使用工具上下文的 EmbeddingResources
  → 首次加载 manifest.json、index.json、vectors.npy，后续复用本轮只读索引
  → 根据清单的 model_id/backend 获取缓存查询模型
  → encode([query])，归一化查询向量并计算 top-k
  → 返回文本、分数与绝对文档引用；工具异常转换为 ok:false
```

HTTP 预检加载索引但不创建查询模型；实际工具执行时另建本轮上下文。`EmbeddingResources` 的锁保证并行查询只初始化一次索引和模型引用。查询模型按模型 ID 与后端缓存在 `embedding.py`；生成端模型缓存独立，不新增公共模型模块。问答不重建文档向量。

- `ls(path="")`：逐层浏览资源的 documents 目录。
- `grep(query, scope="", max_results=20)`：使用 ripgrep 查找 Markdown 候选行。
- `read(path)`：读取真实 Markdown 文件，拒绝文档目录之外的路径。
- `search_embedding(query, top_k=5, scope="")`：沿用资源记录的模型编码 query，从已加载索引召回文本及 covered_files。scope 当前保留参数，尚未限制语义召回范围。

Markdown 文件树由资源模块创建：文档标题作为顶层目录后缀，h1–h6 按层级建目录；paragraph、list、table 分别作为文件。排序使用数字前缀；合并表格单元格展开为 Markdown。内部 index/manifest 不暴露给浏览工具。

检索只提供候选，具体事实应 read 后引用。过程消息使用可读标签链接；最终回答使用句尾数字引用，例如 `[1](/abs/resource/documents/...md)`，不汇总成末尾 Sources 区。非文档问题允许直接回答。

## 跨轮与部署

每轮历史完全来自调用方的 append-only messages，保留 assistant tool_calls 和 tool 结果，不摘要或裁剪。资源路径跨轮稳定；任务与路径的关联由 backend 管理。

本次只完成 agent 契约：问答 HTTP 输入从 documents 改为 resource_path，不接收任务 metadata。backend 尚未迁移。active completion 注册表仍是单进程内存，部署使用单 worker。

接口见 [agent API](../../../docs/API.md)，资源准备见 [资源设计](../../document_resources/docs/DESIGN.md)。
