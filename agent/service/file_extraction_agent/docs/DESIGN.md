# 文档问答执行设计

问答模块消费已准备的资源定位数组，执行一次模型/工具循环。资源生成由同级 `document_resources` 负责；两包互不导入，通过 storage 服务交接。资源读取归工具层，Agent 的 embedding 能力集中在 `tools/embedding.py`。

```text
resource_refs([{type, location}]) + messages + 模型/运行配置
  -> route 将 protobuf 转成普通参数，application.stream_completion 校验 ID/消息后调 tools/worker_client.prepare_workspace 启动 prepare 子进程
       -> worker 按 resource_refs 拉取 documents.zip、加载并校验索引
       -> 返回 workspace payload（归档 bytes + 已解析索引），父进程只保存这份数据
  -> application 装配模型，消费 stream_execution 业务事件流
  -> run_qa_stream 用 workspace 调 build_tools；四个工具只经 worker_client.run_operation
     把 operation、参数和全量 workspace 下发给一次性工具子进程
  -> messages.build_qa_messages 转换历史消息
  -> loop.stream_qa_graph 调 graph.build_qa_graph，绑定 RunOptions 与执行函数
  -> QaState 保存完整 messages 与请求次数、失败信息、退避时长
  -> LangGraph agent 单次请求 / retry_wait 指数退避 / tools 工具节点
  -> loop 消费 graph.astream，转换 messages 增量、updates 模型结果和 custom 单个工具结果，输出类型化通知
  -> application.stream_execution 归一化 core 输出为业务 CompletionEvent，按消费顺序分配 seq
  -> routes/file_extraction_agent.py 中的编码函数 只映射字段并编码 JSON，gRPC 转发 protobuf；application/core 不依赖传输协议
```

schemas.CompletionEvent 使用普通 dataclass，动态 args/result 保留原值；Unset 区分字段缺省与 JSON null。编码器保留显式零值和 false。

## 存储访问

- prepare 子进程通过 `service/object_store`（boto3，endpoint 指向 storage 服务，
  `S3_ENDPOINT_URL` 配置，默认 `http://localhost:9000`）读取资源。
- `load_workspace_payload(resource_refs)` 解析资源定位数组：按 type 找到 documents 与 index 的
  `s3://<bucket>[/<key>]` 位置，GET `documents.zip` 后校验 zip，加载并校验
  `manifest.json` / `index.json` / `vectors.npy`，再把归档 bytes 与已解析索引序列化成
  JSON payload（`documents_archive_b64` + `index`）。
- 父进程从不访问对象存储，也不持有 `ObjectStore` / `DocumentFileTree` / `EmbeddingResources`；
  它只保存 payload，并在每次工具调用时全量下发给新的工具子进程。
- 只读工具子进程用 `document_tree_from_payload(payload)` 从归档 bytes 重建
  `ArchiveObjectStore` 与 `DocumentFileTree`，不访问 storage 服务；索引的 `covered_files`
  在 prepare 阶段已解析成 `documents/...` key。
- `grep` 在工具子进程里用纯 Python 遍历 .md 对象并做忽略大小写的字面匹配，不依赖 ripgrep。

## 请求内执行

application.stream_completion 校验 completion_id 格式、非空 messages 与资源，调用 build_qa_model 后消费 stream_execution。后者迭代 core 类型化输出，解释模型终止信号与工具结果，生成模型事件和对应的 tool_started。路由只做输入转换、输出编码、RPC 错误映射和取消传播。没有 manager、运行时类、独立 producer、锁或队列；completion_id 不再用于活动去重，相同 ID 的 RPC 互不影响。

```text
handler 使用 aclosing 消费 application.stream_completion(completion_id, resource_refs, messages, model_config, run_options)
  → application 预检资源、装配模型，调用 stream_execution(workspace, qa_model, messages, run_options)
  → 输出 completion.created
  → 输出 source_indexed，直接 async for 消费 core.run_qa_stream
  → 模型、工具、重试通知转换成业务事件并逐条编号，路由编码 protobuf
  → 正常结束输出 completion.completed；普通异常输出 completion.failed
  → RPC 取消沿 await 传播，不转换 CancelledError/GeneratorExit，不生成取消终态
  → aclosing 逐层关闭生成器，等待模型和工具清理
```

暂停消费时外层不主动生产；gRPC 负责网络流控。图内部仍可并行运行工具，executor 负责取消未完成子任务。客户端停止消费后应取消原 call；call.cancel 返回不代表远端清理确认。持久化状态、会话和迟到事件写入判断由 backend 管理。

## 执行输入与状态

QaState 继承 MessagesState，增加 model_attempt、model_failure、retry_delay_seconds。只有校验通过的完整消息进入 messages；失败尝试的部分文本不进入历史。workspace payload、运行参数和工具运行参数均在图状态之外。

`run_qa_stream` 是 Agent 接口：校验非空消息和 workspace → build_tools 给四个工具绑定同一份 payload → build_qa_messages 转换完整历史 → 调用同模块 stream_qa_graph 执行图并转换输出。loop 解析图更新，但不决定节点路由；关闭接口流时通过 aclosing 关闭内层生成器，并等待原生图流 aclose。

graph.py 绑定固定模型并编译 agent、retry_wait、tools 三个节点。agent 每次只调用一次 model_invocation；ModelCallFailure 通过 Command 更新状态，未达上限路由至 retry_wait，否则结束。retry_wait 按以 0.5 秒起步、8 秒封顶并乘 0.75–1 随机系数的指数间隔等待后回到 agent；同一逻辑模型调用总共最多五次请求。成功后计数归零，工具完成后的下一次模型调用重新计数。无效工具 ID 抛 ValueError，不发完整消息、不执行工具。

loop.stream_qa_graph 使用 graph.astream(stream_mode=["messages", "updates", "custom"])：messages 通过 LangChain 原生回调提供 chunk，updates 提供节点结束结果，custom 提供节点尚未结束时的单个 ToolMessage；loop 不重复发布 tools 的 updates。只读取 agent 节点的可见文本，过滤隐藏推理和工具参数。每次实际请求首次观察到输出时分配独立 message_id 并发送 MessageStarted，随后 MessageDelta；完成后输出带同一 ID 的完整 AIMessage。没有回调的注入模型仅在完成时输出正文，不伪装为实时生成。

失败结果保留 retry_after_seconds：从响应头优先解析 retry-after-ms，其次 Retry-After 秒数或 HTTP 日期；仅接受有限且大于 0、不超过 120 秒的值，否则回退到随机指数退避。graph 优先采用该值，不叠加抖动。等待时间只计算一次，事件使用同一值换算毫秒。

失败更新转换成 ModelRetry 或 ModelFailed。重试通知在退避结束前输出，携带失败尝试的 message_id、下一次 attempt、max_attempts=5、retry_delay_ms、error；下一次请求使用新 ID。application 将 ModelFailed 转异常，由 stream_execution 统一输出 completion.failed；动态值在输出前校验为合法 JSON，无效值也进入同一失败出口并关闭 core 流；protobuf 编码失败经 athrow 回传业务流，由同一终态出口处理，复用未发送事件的序号。关闭图流传播取消，模型与退避中的 CancelledError 不转换为失败或重试。

RunOptions 只保留 tool_execution_timeout，默认 60 秒；删除从未参与执行的 max_tool_calls。LangGraph 的递归保护仍为 10000，由 graph 内部配置。

application 负责业务校验、prepare_workspace 子进程预检和模型装配；路由只适配 protobuf 与普通参数。首事件前参数错误映射 INVALID_ARGUMENT，其他初始化错误映射 INTERNAL。prepare 取消或失败在 finally kill；source_indexed 仅返回 ok=true，不遍历文档。标准库与内部依赖在顶部导入，重型 embedding 依赖仍延迟加载。

## 循环职责拆分

- loop.py：校验输入 → 初始化工具和消息 → 调用 build_qa_graph → 消费 graph.astream → 合并原生消息增量与节点更新 → 输出类型化通知并关闭图流。
- graph.py：绑定依赖 → 定义 QaState 及模型/退避/工具节点 → 配置路由，取消沿异步等待传播 → 返回编译后的图。
- contracts.py：声明模型/工具 Protocol、BoundModel、AgentOutput 和 JSON 类型。消息使用 LangChain 的具体类型；外部动态工具结果先以 object 接收，再由 messages 归一化为 JsonValue。
- messages.py：完整历史 → 系统提示与角色/工具参数转换 → 模型输入；响应 → 终止信号校验，不完整响应抛 RuntimeError。JSON 归一化供工具结果封装复用。
- model_invocation.py：固定模型与消息 → 单次 astream/ainvoke → 聚合与校验 → AIMessage 或 ModelCallFailure；finally 关闭响应流。重试由 graph 控制。
- executor.py：调用列表和工具集合 → create_task 并发 ainvoke → FIRST_COMPLETED 按共享 deadline 等待 → on_result 立即发布单项 ToolMessage → 按调用顺序返回完整历史；异常/超时转失败结果，取消时清理未完成 Task，不等待迟到线程。

## 消息批次与事件

模型配置来自既有文件/环境配置及显式请求覆盖；ConfiguredChatModel 直接保存单个 provider 和 use_stream，绑定工具后返回 BoundModel；单次调用显式选择 astream 或 ainvoke，不再维护候选列表。生产配置固定 streaming=True，不自动降级。SDK max_retries 固定为 0，避免与图的五次尝试相乘；旧配置字段暂保留解析，但不再控制 SDK 重试。

对外模型事件为 model_message.started、model_message.delta、model_message.done，重试事件为 model_request.retrying。前端按 message_id 追加 delta；done.content 只能确认或替换，不能再次追加。重试标记旧尝试失败，新 ID 开始新正文。done 只代表本条消息完成，整轮仍以 completion 终态为准。协议是消费端行为变更，backend/前端的持久化及显示适配尚未在本次实施。


每条 gRPC 流已绑定本轮请求，所有事件均不重复携带 completion ID；事件包装入口也不接收该参数。completion_id 仅保留请求格式校验，不用于注册、去重或取消。tool_call_id 及模型 tool_calls 内的 ID 仍保留，用于调用与结果配对。

```text
模型节点调用 model_invocation._invoke_model_message
  → 校验响应完整性及工具 ID 唯一性
  → yield AIMessage
  → application 输出 model_message.done；有调用则输出 tool_started

工具节点调用 executor._execute_tools_parallel
  → asyncio.create_task 并发执行整批工具协程
  → 按共享 deadline 和原始顺序收集成功 / 异常 / 超时结果
  → 每项 ToolMessage 携带 tool_call_id、name、additional_kwargs.tool_args、artifact、status
  → 每项完成经 on_result → graph custom → loop yield ToolMessage
  → 全部完成后才将完整结果写入图状态，供下一轮模型使用
  → application 输出 tool_completed / tool_failed
```

事件包装不维护 pending 配对字典。工具节点按调用 ID 保留已发布的完整 ToolMessage；执行器异常时仅为未发布项补失败结果，再按原调用顺序写入模型历史，已发布结果不覆盖、不重复输出。普通模型调用失败在图中指数退避，五次耗尽后通过 ModelFailed 以 completion.failed 收口。

消息仅提取可见文本，不输出隐藏推理。合法 terminal stop signal 且无 tool_calls 时标记 is_final=true。图更新不重复输出历史消息或最后一条回答。

## 取消与进程边界

```text
客户端取消原 ChatCompletion call / deadline / 检测到断连
  → grpc.aio 取消 handler
  → 当前 await 收到 CancelledError，传播到模型/图执行
  → handler 的 aclosing 关闭 stream_completion 及内层生成器
  → executor 清理未完成工具 Task；run_operation finally kill 工具子进程
  → 执行退出，不交付取消终态
```

取消不会撤回已经交付的事件或副作用，也不强制中断同步代码。清理时间没有固定保证；backend 自行提交业务取消状态并拒绝迟到写入。prepare 阶段取消同样清理子进程。所有执行都绑定本次 RPC，不通过 ID 注册或查找运行时。

## 工具与引用

工具对模型暴露 async coroutine；executor 只 await `ainvoke`。每个工具调用都会经 `worker_client.run_operation` 启动一次性工具子进程，把 operation、参数和全量 workspace payload 经 stdin 下发；父进程不执行任何对象读取或推理计算。

工具各自使用单文件：`tools/ls.py`、`grep.py`、`read.py`、`embedding.py`；统一子进程入口是 `tools/worker.py`（operation 分发），父进程客户端在 `tools/worker_client.py`，纯 OpenVINO 查询编码器在 `tools/ov_embedder.py`。归档与 payload 序列化在 `workspace.py`，异常结果归一化在 `base.py`。

run_tool 只接收 execute 操作，正常返回结果，普通异常转为 ok:false。工具工厂直接使用必需的 LangChain @tool，返回 BaseTool；不保留缺依赖时退化为普通函数的分支。

```text
prepare_workspace(resource_refs)
  -> 空数组直接抛 ValueError；否则启动 python -m ...tools.worker 执行 prepare
  -> worker: load_workspace_payload 拉取归档、校验清单版本/模型/向量/引用
  -> 返回 {ok, workspace:{bucket, documents_archive_b64, index}}
  -> kind=invalid 映射 ValueError（INVALID_ARGUMENT）；其他失败映射 RuntimeError（INTERNAL）
  -> 取消/超时/失败都在 finally kill 子进程

ls / grep / read / search_embedding
  -> 父进程 run_operation 组装 {operation, args, workspace}
  -> worker 分发：只读工具用 document_tree_from_payload 重建文档树；
     search_embedding 从 workspace.index 解码 chunks/vectors 后加载 OpenVINO 编码器
  -> worker stdout 返回工具 JSON；进程级失败转为 ok:false 与 errors
  -> 取消/超时/失败都在 finally kill 子进程
```

查询模型不在父进程加载；prepare 子进程只加载并校验索引，检索子进程按需加载 OpenVINO 编码器。查询编码只依赖 openvino + tokenizers，不 import torch/transformers；生成端索引构建仍用 sentence-transformers。问答不重建文档向量。

基准（本机、OpenVINO CPU、默认模型，实测）：检索子进程每次启动约 2.3s、峰值内存约 420MB，稳态编码约 3ms/条；对比 sentence-transformers 包装启动约 21s。当前按“每次工具调用一个进程”换取可 kill 的取消语义与实现简单，不引入常驻 worker，也不限制并发。

- `ls(path="")`：在工具子进程里逐层浏览归档的 documents 目录。
- `grep(query, scope="", max_results=20)`：在工具子进程里纯 Python 遍历 .md 对象并做忽略大小写的字面匹配候选行。
- `read(path)`：在工具子进程里读取真实 Markdown 文件，拒绝文档目录之外的路径。
- `search_embedding(query, top_k=5)`：沿用资源记录的模型，在一次性子进程里用纯 OpenVINO 编码 query，从 payload 索引召回文本及 covered_files；子进程可被取消 kill，删除从未参与过滤的 scope 参数。

Markdown 文件树由资源模块创建：文档标题作为顶层目录后缀，h1–h6 按层级建目录；paragraph、list、table 分别作为文件。排序使用数字前缀；合并表格单元格展开为 Markdown。内部 index/manifest 不暴露给浏览工具。

检索只提供候选，具体事实应 read 后引用。过程消息使用可读标签链接；最终回答使用句尾数字引用，例如 `[1](documents/0001-contract/0001-section/0001-block.md)`，链接目标原样使用工具返回的 key，不汇总成末尾 Sources 区。非文档问题允许直接回答。

资源定位与工具路径是两层：RPC 的 `resource_path`（文中也称 resource_refs）保存
`s3://res_example/documents` 与 `s3://res_example/index`；工具工作区固定 bucket 后，
ls/read/grep 与检索结果使用 `documents/...` key，不传本机绝对路径或完整 S3 URL。
引用链接保存同一个 key；它不是可直接访问的 HTTP 下载地址，展示端需结合资源定位解析。
完整输入输出示例见 [工具说明](tools.md)。

## 跨轮与部署

每轮历史完全来自调用方的 append-only messages，保留 assistant tool_calls 和 tool 结果，不摘要或裁剪。资源定位数组跨轮稳定；任务与定位的关联由 backend 管理。

本次将 agent 对外传输改为 gRPC；问答仍接收资源定位数组，不接收任务 metadata。backend 尚未迁移。每个 RPC 直接持有自己的执行流，不维护活动 completion 注册表。

接口见 [agent API](../../../docs/API.md)，资源准备见 [资源设计](../../document_resources/docs/DESIGN.md)。

## 模型装配与文本归一化

```text
ModelConfig 或环境变量
  → 校验 provider 与 api_transport
  → _chat_model_class 延迟加载标准 ChatOpenAI
  → use_responses_api 选择 Responses / Chat Completions，SDK 重试固定关闭
  → ConfiguredChatModel 保存单个 provider，bind_tools 返回 BoundModel
  → model_invocation 按 use_stream 调用并校验完整消息
```

已删除 openai_models.py 和 DeepSeek 专用 reasoning_content 保存/回传及 thinking 参数注入；reasoning_effort 等通用配置继续按标准 SDK 传入。重试由图统一控制。工具契约仅支持 ainvoke，不再声明同步工具。

messages.visible_text 统一处理增量和完整消息：字符串直接返回，列表只保留字符串和 text 块中的字符串，忽略推理、非文本块及无效 text 值。取消仅依赖 Task/生成器关闭，不再传递 should_stop 回调；模型流关闭、工具子任务取消和子进程清理继续保留。
