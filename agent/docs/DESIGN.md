# Agent Service Design

agent 在同一个进程中提供两个阶段：准备可复用的本机文档资源，以及基于资源路径执行一次问答。多轮会话、任务与事件持久化由 backend 管理。

```text
POST /v1/document-resources（files）
  → document_processor.process：PDF / DOCX → filename + html
  → document_resources.prepare_resources：HTML → Markdown 文件树 → 文档 embedding 索引
  → 返回 resource_path + documents，调用方保存路径和展示用 HTML

POST /v1/document-qa/chat/completions（resource_path + messages）
  → CompletionManager 委托工具层预检资源并注册 completion
  → graph 保存路径和消息；build_tools 创建工具访问上下文
  → 模型消息 / 完整工具结果批次
  → manager 包装事件，ActiveCompletion 编码 SSE
  → 释放本轮运行时，保留文档资源
```

## 模块边界

| 模块 | 职责 |
| --- | --- |
| routes/document_resources.py | 校验上传类型，在线程池中串联解析与资源准备，映射 HTTP 错误 |
| service/document_processor | PDF 调 MinerU、DOCX 调 python-docx，输出带 CSS 的 HTML |
| service/document_resources | HTML 转文件、文档分块和 embedding 索引构建、资源落盘与发布前自检 |
| routes/file_extraction_agent.py | 路径问答、取消 HTTP 适配 |
| service/file_extraction_agent/manager.py | completion 注册、取消、事件包装与 SSE；不生成文档状态 |
| service/file_extraction_agent/core/graph.py | 构造仅含 resource_path、messages、RunOptions 的 GraphState |
| service/file_extraction_agent/core/loop.py | LangGraph 模型/工具循环；工具结果整批返回 |
| service/file_extraction_agent/core/tools/workspace.py | 资源目录预检、文件浏览与读取、文档树数据 |
| service/file_extraction_agent/core/tools/embedding.py | 清单配置和索引读取、查询模型缓存、query 编码与检索 |

两个业务包通过磁盘格式交接，互不导入。`document_resources` 只生成资源；问答读取由工具层负责。

## 资源生命周期

- 准备和问答共享本机文件系统。backend 只保存、回传路径，不需要读取 agent 磁盘。
- `DOCUMENT_RESOURCES_ROOT` 指定资源根目录，默认 `agent/data/resources`。
- 每次准备生成独立 `res_*` 目录；临时目录完成校验后才发布。解析或构建失败不返回半成品路径。
- 资源含 `documents/`、`index/`、`manifest.json`。模型只能浏览 `documents/`，索引引用保存相对路径。
- manifest 固定 embedding 模型、后端和分块配置。问答加载已有索引，仅对 query 做 embedding，不重建文档向量。
- 问答完成、失败、取消都不删除资源。首版不做内容去重、自动过期和删除 API；资源管理不依赖 task_id。

## 问答运行时

`CompletionManager` 只在进程内保存 active completion；管理 ID 不进入 graph。GraphState 只保存资源路径、历史消息和运行配置。工具闭包持有 ToolWorkspace；其中的 EmbeddingResources 管理本轮索引与查询模型引用。

```text
模型节点返回 AIMessage
  → manager 输出 model_message 和 tool_started
  → 工具节点并行执行，按共享 deadline 收集整批 ToolMessage
  → 每项携带调用 ID、名称、参数和成功/失败结果
  → manager 直接输出 tool_completed / tool_failed，不维护 pending 配对字典
```

取消保持已发布调用的结果完整性：没有活动批次时立即唤醒 SSE consumer；已有批次时消费完结果再结束，不调用下一轮模型。队列按 FIFO 发出已提交事件，终态只提交一次。资源校验错误在 HTTP 响应开始前返回 422；执行异常通过 completion.failed 收口。

## 对外契约与迁移

- 准备接口：`POST /v1/document-resources`，多文件 multipart，返回路径和各文件 HTML。
- 问答接口：`POST /v1/document-qa/chat/completions`，用 resource_path 替换 documents，不接收任务 metadata。
- 保留 healthz、能力查询及 completion cancel；completion GET 仍为占位接口。
- 旧 `/v1/document-processor/process` 已删除，不保留旧问答 documents 输入。
- 本次只修改 agent；backend 尚未适配，现有 backend 需后续切换上传及问答请求契约。
- cancel 注册表依赖单进程，仍按单 worker 部署。

接口示例见 [API.md](API.md)，资源细节见 [资源设计](../service/document_resources/docs/DESIGN.md)，问答细节见 [问答设计](../service/file_extraction_agent/docs/DESIGN.md)。
