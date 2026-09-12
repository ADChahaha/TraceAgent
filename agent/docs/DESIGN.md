# Agent Service Design

agent 在同一个进程中提供两个阶段：准备可复用的本机文档资源，以及基于资源路径执行一次问答。多轮会话、任务与事件持久化由 backend 管理。

```text
PrepareResources（files: filename + bytes）
  → document_processor.process：PDF / DOCX → filename + html
  → document_resources.prepare_resources：HTML → Markdown 文件树 → 文档 embedding 索引
  → 发布到独立的 storage 服务（S3 兼容），返回资源定位数组 [{type, location}]
     documents 文件树打成单个 documents.zip，index/raw 各自独立对象
     type ∈ {documents, index, raw}，location 为 s3://<bucket>[/<key>]

ChatCompletion（resource_refs + messages）
  → CompletionManager 委托工具层预检资源并注册 completion
  → 经 S3ObjectStore（boto3）从 storage 服务读取资源
  → 路径创建工具上下文，运行配置绑定执行器，图内保存完整 messages 和重试状态
  → 模型文本增量 / 完整消息 / 重试通知 / 单个工具结果
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
| service/document_resources | HTML 转文件、文档分块和 embedding 索引构建、发布到 storage 服务 |
| routes/file_extraction_agent.py | 路径问答、取消 gRPC 适配；固定字段转 protobuf，动态字段保留 JSON |
| service/file_extraction_agent/manager.py | completion 创建、注册、查找、取消转发与流结束后的移除 |
| service/file_extraction_agent/completion_runtime.py | 单轮执行、事件字典输出、生产协程与取消收尾 |
| service/file_extraction_agent/core/loop.py | Agent 接口：校验输入、组装工作区/工具/历史消息、执行图并转换原生流输出、关闭图流 |
| service/file_extraction_agent/core/contracts.py | 模型与工具调用协议、消息输出和 JSON 类型，不承担执行 |
| service/file_extraction_agent/core/messages.py | 提示词、历史转换、响应校验、终止信号与消息 JSON 归一化 |
| service/file_extraction_agent/core/model_invocation.py | 单次模型调用、流式聚合和失败结果 |
| service/file_extraction_agent/core/executor.py | 工具并行执行、共享超时、逐项结果回调与取消清理 |
| service/file_extraction_agent/core/graph.py | LangGraph 状态、单次请求/指数退避/工具节点、路由及节点停止检查 |
| service/file_extraction_agent/core/tools/workspace.py | 资源定位解析、documents.zip 拉取、workspace payload 序列化与还原 |
| service/file_extraction_agent/core/tools/worker_client.py | 父进程侧工具子进程客户端：组装请求、等待响应、finally kill |
| service/file_extraction_agent/core/tools/embedding.py | 清单配置和索引读取校验、payload 序列化与检索工具工厂 |
| service/file_extraction_agent/core/tools/worker.py | 统一工具子进程入口：operation 分发 prepare/ls/grep/read/search_embedding |
| service/file_extraction_agent/core/tools/ov_embedder.py | 纯 OpenVINO 查询编码器（tokenizer + IR + mean pooling + L2） |
| service/object_store.py | ObjectStore 接口 + S3ObjectStore（boto3）+ Archive/Composite store + s3:// URL 解析 |

两个业务包通过 storage 服务交接，互不导入。`document_resources` 只生成并发布资源；问答在 prepare 与工具子进程内经 S3ObjectStore 读取。

## 传输与部署

```text
main.py 读取监听地址、阻塞工作线程数和消息上限
  → asyncio.run 创建事件循环，启动 grpc.aio.Server 与异步标准 Health
  → PrepareResources 的解析/资源构建通过 asyncio.to_thread 执行
  → ChatCompletion 的资源预检和每个工具调用通过一次性 worker 子进程执行
  → 取消和探活直接在事件循环处理
  → routes 转换 protobuf 与业务对象，保留参数缺省值及显式零值
  → producer 将事件放入 asyncio.Queue，队列自动唤醒消费者
  → runtime.astream 按 FIFO 分配 seq，routes 用 async for 编码 CompletionEvent
  → SIGINT/SIGTERM 唤醒 asyncio.Event，await server.stop(5) 停服
```

默认 16 个阻塞工作线程、单条请求/响应上限 64 MiB。活动 RPC 流不受线程数限制，等待事件不占执行器；模型请求、重试退避、图执行和工具调度均为原生异步；文档解析使用阻塞工作线程，工具计算在可 kill 的子进程中执行。文件整包 bytes 上传，客户端须相应配置收发上限。固定事件字段使用 protobuf，动态参数/结果用 JSON 字符串保留大整数和 null。共享协议位于与 agent 同级的 agent_proto，agent wheel 依赖 traceagent-protocol，不内置协议副本。协议生成器版本固定，从仓库根目录生成；测试比对绑定，并验证共享 wheel 可脱离 agent 业务包导入。

传输层断连与业务取消分开：CancelCompletion 立即确认并取消 producer 和未完成工具 Task；RPC 取消/断连/deadline 回调绑定本轮 CompletionRuntime 的 close，设置取消信号并取消 producer，finally 仅 await runtime.aclose，由 runtime 关闭所持事件生成器、等待 producer 清理并通知 manager 移除注册项。旧回调不会按 ID 误取消后来的新流；从未迭代的流关闭也会清理。断连后不保证交付终态，取消生产协程并关闭模型流，工具子进程会被 kill。

问答初始化不再有需要跨线程交接的同步工作：prepare 子进程在取消时被 kill，之后才注册运行时；初始化失败或取消不会留下注册项。

## 资源生命周期

- 资源和问答都通过独立的 storage 服务（S3 兼容 HTTP，仓库顶层 `storage/` 目录）存取。
- 每次准备生成独立 bucket `res_*`；本机临时目录完成校验后才开始逐对象上传。构建或校验失败不上传；上传失败可能留下远端部分对象，不返回资源定位。当前没有远端回滚或原子发布机制，本地临时目录在成功或失败后均清理。
- 资源含文档树归档 `documents.zip`（成员为 `documents/...` 逻辑路径）、`index/`、
  `manifest.json`，以及 `raw/<filename>` 原始文件。读取端把归档整包解到内存虚拟文件系统，
  模型只能浏览 `documents/`，索引引用保存相对路径。
- manifest 固定 embedding 模型、后端和分块配置。问答加载已有索引，仅对 query 做 embedding，不重建文档向量。
- 问答完成、失败、取消都不删除资源。首版不做内容去重、自动过期和删除 API；资源管理不依赖 task_id。
- agent 通过 `service/object_store.S3ObjectStore`（boto3）访问 storage 服务，
  endpoint 由 `S3_ENDPOINT_URL` 配置，默认 `http://localhost:9000`。

## 问答运行时

`CompletionManager` 只在进程内保存 active completion；管理 ID 不进入 graph。图使用继承 MessagesState 的 QaState，保存完整消息和重试控制状态；路由层先经 prepare 子进程取得 workspace payload（归档 bytes + 已解析索引），RunOptions 在构图时绑定工具执行器。父进程不持有 ToolWorkspace 或索引；四个工具只经 worker_client 把 payload 下发给一次性子进程。

```text
模型节点返回 AIMessage
  → completion_runtime 输出 model_message.started/delta/done、重试通知和 tool_started
  → 工具节点并行执行，按共享 deadline 逐项经 custom 输出 ToolMessage，完整历史供下一轮模型使用
  → 每项携带调用 ID、名称、参数和成功/失败结果
  → completion_runtime 直接输出 tool_completed / tool_failed，不维护 pending 配对字典
```

取消立即唤醒 consumer 并取消 producer，工具 finally 取消未完成 Task，run_operation finally kill 工具子进程；不配齐中断结果、不调用下一轮模型。正常消费按 FIFO 输出，astream 独自生成完成/失败；取消丢弃未消费事件并直接关闭，不发取消终态。资源校验错误在首事件前返回 INVALID_ARGUMENT；执行异常通过 completion.failed 收口。

## 对外契约与迁移

- 准备接口：`PrepareResources`，一次发送多个 filename/bytes，返回资源定位数组（文档树为 `documents.zip` 归档，不再内联返回 HTML）。
- 问答接口：`ChatCompletion`，resource_refs（[{type, location}]）+ messages 输入，CompletionEvent 服务端流输出。
- 采用标准 gRPC Health 探活；业务 RPC 仅提供 PrepareResources、ChatCompletion、CancelCompletion。问答进展与终态由事件流交付，不提供问答查询或能力查询 RPC。
- 不再提供 FastAPI、HTTP 路由和 SSE；旧问答 documents 输入不保留。
- 本次迁移 agent 及其启动脚本/CI 配套；backend 代码未改，旧 HTTP 客户端需后续适配。
- cancel 注册表依赖单进程；多个 RPC 协程共享 manager，多进程之间不共享取消状态。

接口示例见 [API.md](API.md)，资源细节见 [资源设计](../service/document_resources/docs/DESIGN.md)，问答细节见 [问答设计](../service/file_extraction_agent/docs/DESIGN.md)。
