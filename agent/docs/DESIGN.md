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
  → 路由调用 prepare_workspace 预检资源，校验消息并装配模型
  → 经 S3ObjectStore（boto3）从 storage 服务读取资源
  → 路径创建工具上下文，运行配置绑定执行器，图内保存完整 messages 和重试状态
  → 模型文本增量 / 完整消息 / 重试通知 / 单个工具结果
  → routes/file_extraction_agent.stream_completion 直接构造不含 completion ID、带 seq 的 CompletionEvent
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
| routes/file_extraction_agent.py | 校验与装配；直接将 core 输出编码为 protobuf，分配 seq、处理终态并关闭内层流；动态字段保留 JSON |
| service/file_extraction_agent/core/loop.py | Agent 接口：校验输入、组装工作区/工具/历史消息、执行图并转换原生流输出、关闭图流 |
| service/file_extraction_agent/core/contracts.py | 模型与工具调用协议、单一 BoundModel、异步工具、消息输出和 JSON 类型，不承担执行 |
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
  → handler 直接消费 stream_completion，按顺序分配 seq 并编码 CompletionEvent
  → handler 使用 aclosing 关闭生成器，RPC 取消沿 await 传播
  → SIGINT/SIGTERM 唤醒 asyncio.Event，await server.stop(5) 停服
```

默认 16 个阻塞工作线程、单条请求/响应上限 64 MiB。活动 RPC 流不受线程数限制，等待事件不占执行器；模型请求、重试退避、图执行和工具调度均为原生异步；文档解析使用阻塞工作线程，工具计算在可 kill 的子进程中执行。文件整包 bytes 上传，客户端须相应配置收发上限。固定事件字段使用 protobuf，动态参数/结果用 JSON 字符串保留大整数和 null。共享协议位于与 agent 同级的 agent_proto，agent wheel 依赖 traceagent-protocol，不内置协议副本。协议生成器版本固定，从仓库根目录生成；测试比对绑定，并验证共享 wheel 可脱离 agent 业务包导入。

一次 ChatCompletion RPC 持有一轮执行。客户端取消原 call、deadline 或已检测到的断连由 grpc.aio 取消 handler；handler 关闭事件流，取消沿模型/图等待传播，工具 finally 取消未完成 Task 并 kill 工具子进程。没有独立 producer、事件队列、注册表或 CancelCompletion RPC。客户端本地取消不代表远端清理已经完成，backend 仍须拒绝旧轮迟到写入。

prepare 子进程同样在取消时清理；已创建但未消费的生成器不启动模型执行。

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

`routes/file_extraction_agent.stream_completion(workspace, qa_model, messages, run_options)` 是普通异步生成器函数，直接消费 `core.loop.run_qa_stream` 的类型化输出并生成 protobuf，不经过字典事件层。路由负责输入校验、模型装配和资源预检；图使用 QaState 保存消息与重试状态，工具只接收本轮 workspace payload。不同 RPC 不共享可变执行状态；completion_id 保留格式校验，但不用于注册、去重或取消。

```text
模型节点返回 AIMessage
  → 路由直接输出 model_message.started/delta/done、重试通知和 tool_started
  → 工具节点并行执行，按共享 deadline 逐项经 custom 输出 ToolMessage，完整历史供下一轮模型使用
  → 每项携带调用 ID、名称、参数和成功/失败结果
  → 路由直接输出 tool_completed / tool_failed，不维护 pending 配对字典
```

正常完成输出 completion.completed；普通执行异常输出 completion.failed；CancelledError/GeneratorExit 直接传播，不补发终态。生成器逐层关闭，工具 finally 清理子进程。资源参数错误在首事件前返回 INVALID_ARGUMENT。

## 对外契约与迁移

- 准备接口：`PrepareResources`，一次发送多个 filename/bytes，返回资源定位数组（文档树为 `documents.zip` 归档，不再内联返回 HTML）。
- 问答接口：`ChatCompletion`，resource_refs（[{type, location}]）+ messages 输入，CompletionEvent 服务端流输出。
- 采用标准 gRPC Health 探活；业务 RPC 仅提供 PrepareResources、ChatCompletion。问答进展与终态由事件流交付，不提供问答查询或能力查询 RPC。
- 不再提供 FastAPI、HTTP 路由和 SSE；旧问答 documents 输入不保留。
- 本次迁移 agent 及其启动脚本/CI 配套；backend 代码未改，旧 HTTP 客户端需后续适配。
- 取消通过原 gRPC call 定位执行，不需要跨实例按 completion ID 路由。

接口示例见 [API.md](API.md)，资源细节见 [资源设计](../service/document_resources/docs/DESIGN.md)，问答细节见 [问答设计](../service/file_extraction_agent/docs/DESIGN.md)。

模型装配仅保存一个 provider 和调用方式，工具契约仅支持异步调用。取消沿 Task 传播，不再额外传递停止标志；可见文本统一由 messages.visible_text 提取。已移除 DeepSeek 专用模型适配，所有模型使用标准 ChatOpenAI。
