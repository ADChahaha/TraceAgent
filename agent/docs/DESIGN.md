# Agent Service Design

agent 在同一个进程中提供两个阶段：准备可复用的本机文档资源，以及基于资源路径执行一次问答。多轮会话、任务与事件持久化由 backend 管理。

```text
PrepareResources（files: filename + bytes）
  → document_processor.process：PDF / DOCX → filename + html
  → document_resources.prepare_resources：HTML → Markdown 文件树 → 文档 embedding 索引
  → 返回 resource_path + documents，调用方保存路径和展示用 HTML

ChatCompletion（resource_path + messages）
  → CompletionManager 委托工具层预检资源并注册 completion
  → 路径创建工具上下文，运行配置绑定执行器，图内只保存 messages
  → 模型消息 / 完整工具结果批次
  → completion_runtime 输出不含 completion ID、带 seq 的事件字典，由传输层编码
  → 释放本轮运行时，保留文档资源
```

## 模块边界

| 模块 | 职责 |
| --- | --- |
| ../agent_proto/agent.proto | 仓库根目录的共享契约；独立发布 traceagent-protocol，agent/backend 均可依赖 |
| main.py | grpc.aio 启停、阻塞工作执行器、消息大小配置、异步 Health 与 CLI 探活 |
| routes/__init__.py | 注册异步业务方法，通过 async for 转发问答流 |
| routes/document_resources.py | 在线程中校验上传类型、解析与准备资源，回到事件循环映射 RPC 错误 |
| service/document_processor | PDF 调 MinerU、DOCX 调 python-docx，输出带 CSS 的 HTML |
| service/document_resources | HTML 转文件、文档分块和 embedding 索引构建、资源落盘与发布前自检 |
| routes/file_extraction_agent.py | 路径问答、取消 gRPC 适配；固定字段转 protobuf，动态字段保留 JSON |
| service/file_extraction_agent/manager.py | completion 创建、注册、查找、取消转发与流结束后的移除 |
| service/file_extraction_agent/completion_runtime.py | 单轮执行、事件字典输出、生产协程与取消收尾 |
| service/file_extraction_agent/core/loop.py | 初始化依赖、消费图更新、批次转发与取消关闭 |
| service/file_extraction_agent/core/messages.py | 提示词、历史转换、响应校验、终止信号与消息 JSON 归一化 |
| service/file_extraction_agent/core/model_invocation.py | 模型调用、流式聚合、重试与退避 |
| service/file_extraction_agent/core/executor.py | 工具并行执行、共享超时与 ToolMessage 封装 |
| service/file_extraction_agent/core/graph.py | 绑定 agent/tools 节点、条件路由，编译 MessagesState 图 |
| service/file_extraction_agent/core/tools/workspace.py | 资源目录预检、文件浏览与读取 |
| service/file_extraction_agent/core/tools/embedding.py | 清单配置和索引读取、查询模型缓存、query 编码与检索 |

两个业务包通过磁盘格式交接，互不导入。`document_resources` 只生成资源；问答读取由工具层负责。

## 传输与部署

```text
main.py 读取监听地址、阻塞工作线程数和消息上限
  → asyncio.run 创建事件循环，启动 grpc.aio.Server 与异步标准 Health
  → PrepareResources 的解析/资源构建、ChatCompletion 的初始化通过 asyncio.to_thread 执行
  → 取消和探活直接在事件循环处理
  → routes 转换 protobuf 与业务对象，保留参数缺省值及显式零值
  → producer 入队后用 call_soon_threadsafe 唤醒 asyncio.Event
  → runtime.astream 按 FIFO 分配 seq，routes 用 async for 编码 CompletionEvent
  → SIGINT/SIGTERM 唤醒 asyncio.Event，await server.stop(5) 停服
```

默认 16 个阻塞工作线程、单条请求/响应上限 64 MiB。活动 RPC 流不受线程数限制，等待事件不占执行器；模型请求、重试退避、图执行和工具调度均为原生异步；文件 I/O 与本地计算才使用阻塞工作线程。文件整包 bytes 上传，客户端须相应配置收发上限。固定事件字段使用 protobuf，动态参数/结果用 JSON 字符串保留大整数和 null。共享协议位于与 agent 同级的 agent_proto，agent wheel 依赖 traceagent-protocol，不内置协议副本。协议生成器版本固定，从仓库根目录生成；测试比对绑定，并验证共享 wheel 可脱离 agent 业务包导入。

传输层断连与业务取消分开：CancelCompletion 立即确认后让原流按批次收尾；RPC 取消/断连/deadline 回调绑定本轮 CompletionStream，唤醒 consumer 并设置停止信号，finally 关闭内层流并移除对应注册项。旧回调不会按 ID 误取消后来的新流；从未迭代的流关闭也会清理。断连后不保证交付终态，取消生产协程并关闭模型流，工具内已运行的同步线程不能强杀。

同步初始化与协程取消通过锁交接流：取消先发生时，初始化线程关闭迟到的流；初始化先完成时，由取消分支关闭已交接流。清理不依赖已关闭事件循环的回调。停服后 asyncio.run 会等待默认执行器中已运行的同步工作结束，5 秒 RPC 宽限期不是进程退出时间的硬上限。

## 资源生命周期

- 准备和问答共享本机文件系统。backend 只保存、回传路径，不需要读取 agent 磁盘。
- `DOCUMENT_RESOURCES_ROOT` 指定资源根目录，默认 `agent/data/resources`。
- 每次准备生成独立 `res_*` 目录；临时目录完成校验后才发布。解析或构建失败不返回半成品路径。
- 资源含 `documents/`、`index/`、`manifest.json`。模型只能浏览 `documents/`，索引引用保存相对路径。
- manifest 固定 embedding 模型、后端和分块配置。问答加载已有索引，仅对 query 做 embedding，不重建文档向量。
- 问答完成、失败、取消都不删除资源。首版不做内容去重、自动过期和删除 API；资源管理不依赖 task_id。

## 问答运行时

`CompletionManager` 只在进程内保存 active completion；管理 ID 不进入 graph。图使用 LangGraph MessagesState，仅保存消息；resource_path 用于创建工具上下文，RunOptions 在构图时绑定工具执行器。工具闭包持有 ToolWorkspace；其中的 EmbeddingResources 管理本轮索引与查询模型引用。

```text
模型节点返回 AIMessage
  → completion_runtime 输出 model_message 和 tool_started
  → 工具节点并行执行，按共享 deadline 收集整批 ToolMessage
  → 每项携带调用 ID、名称、参数和成功/失败结果
  → completion_runtime 直接输出 tool_completed / tool_failed，不维护 pending 配对字典
```

取消保持已发布调用的结果完整性：没有活动批次时立即唤醒事件 consumer；已有批次时消费完结果再结束，不调用下一轮模型。队列按 FIFO 发出已提交事件，终态只提交一次。资源校验错误在首事件前返回 INVALID_ARGUMENT；执行异常通过 completion.failed 收口。

## 对外契约与迁移

- 准备接口：`PrepareResources`，一次发送多个 filename/bytes，返回路径和各文件 HTML。
- 问答接口：`ChatCompletion`，resource_path + messages 输入，CompletionEvent 服务端流输出。
- 采用标准 gRPC Health 探活；业务 RPC 仅提供 PrepareResources、ChatCompletion、CancelCompletion。问答进展与终态由事件流交付，不提供问答查询或能力查询 RPC。
- 不再提供 FastAPI、HTTP 路由和 SSE；旧问答 documents 输入不保留。
- 本次迁移 agent 及其启动脚本/CI 配套；backend 代码未改，旧 HTTP 客户端需后续适配。
- cancel 注册表依赖单进程；多个 RPC 协程共享 manager，多进程之间不共享取消状态。

接口示例见 [API.md](API.md)，资源细节见 [资源设计](../service/document_resources/docs/DESIGN.md)，问答细节见 [问答设计](../service/file_extraction_agent/docs/DESIGN.md)。
