# Agent 模块边界

返回 [Agent Service Design](../DESIGN.md)。

## 核心模块表

| 模块 | 职责 |
| --- | --- |
| `../agent_proto/agent.proto` | 仓库根目录的共享契约；独立发布 `traceagent-protocol`，agent/backend 均可依赖 |
| `main.py` | agent service 的 `grpc.aio` 启停、阻塞工作执行器、消息大小配置、异步 Health 与 CLI 探活 |
| `document_service/main.py` | document service 的 `grpc.aio` 启停、文档处理工作执行器、消息大小配置、异步 Health 与 CLI 探活 |
| `routes/__init__.py` | 注册异步业务方法，通过 `async for` 转发问答流 |
| `document_service/routes.py` | `DocumentResourceService` protobuf 转 `UploadedFile`，在线程中调用上传入口，编码响应并映射 RPC 错误 |
| `../document_service/document_resources/application.py` | 校验上传批次，调用 processor 解析，再调用 `prepare_resources` 发布 |
| `../document_service/document_processor` | PDF 调 MinerU、DOCX 调 python-docx，输出带 CSS 的 HTML |
| `../document_service/document_resources` | HTML 转文件、文档分块和 embedding 索引构建、发布到 storage 服务 |
| `routes/file_extraction_agent.py` | protobuf 转普通参数，调用 application，编码输出并映射 RPC 错误、传播取消 |
| `service/file_extraction_agent/application.py` | 校验与资源预检、模型装配、core 输出归一化、事件编号与唯一终态 |
| `service/file_extraction_agent/core/loop.py` | Agent 接口：校验输入、组装工作区/工具/历史消息、执行图并转换原生流输出、关闭图流 |
| `service/file_extraction_agent/core/contracts.py` | 模型与工具调用协议、单一 `BoundModel`、异步工具、消息输出和 JSON 类型，不承担执行 |
| `service/file_extraction_agent/core/messages.py` | 提示词、历史转换、响应校验、终止信号与消息 JSON 归一化 |
| `service/file_extraction_agent/core/model_invocation.py` | 单次模型调用、流式聚合和失败结果 |
| `service/file_extraction_agent/core/executor.py` | 工具并行执行、共享超时、逐项结果回调与取消清理 |
| `service/file_extraction_agent/core/graph.py` | LangGraph 状态、单次请求/指数退避/工具节点、路由及节点停止检查 |
| `service/file_extraction_agent/core/tools/workspace.py` | 资源定位解析、`documents.zip` 拉取、workspace payload 序列化与还原 |
| `service/file_extraction_agent/core/tools/worker_client.py` | 父进程侧工具子进程客户端：组装请求、等待响应、`finally` kill |
| `service/file_extraction_agent/core/tools/embedding.py` | 清单配置和索引读取校验、payload 序列化与检索工具工厂 |
| `service/file_extraction_agent/core/tools/worker.py` | 统一工具子进程入口：operation 分发 `prepare`/`ls`/`grep`/`read`/`search_embedding` |
| `service/file_extraction_agent/core/tools/ov_embedder.py` | 纯 OpenVINO 查询编码器（tokenizer + IR + mean pooling + L2） |
| `service/object_store.py` | `ObjectStore` 接口 + `S3ObjectStore`（boto3）+ Archive/Composite store + `s3://` URL 解析 |

## 服务交接

- 两个业务服务通过 `storage` 服务交接，互不通过 Python import 交接。
- document service 只生成并发布资源；agent service 在 prepare 与工具子进程内经 `S3ObjectStore` 读取。
