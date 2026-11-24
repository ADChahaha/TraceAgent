# 资源生命周期、问答运行时与对外契约

返回 [Agent Service Design](../DESIGN.md)。

## 资源生命周期

- 资源和问答都通过独立的 `storage` 服务（S3 兼容 HTTP，仓库顶层 `storage/` 目录）存取。
- 每次准备生成独立 bucket `res_*`；本机临时目录完成校验后才开始逐对象上传。构建或校验失败不上传；上传失败可能留下远端部分对象，不返回资源定位。当前没有远端回滚或原子发布机制，本地临时目录在成功或失败后均清理。
- 资源含文档树归档 `documents.zip`（成员为 `documents/...` 逻辑路径）、`index/`、`manifest.json` 及 `raw/<filename>` 原始文件。读取端把归档整包解到内存虚拟文件系统，模型只能浏览 `documents/`，索引引用保存相对路径。
- manifest 固定 embedding 模型、后端和分块配置。问答加载已有索引，仅对 query 做 embedding，不重建文档向量。
- 问答完成、失败、取消都不删除资源。首版不做内容去重、自动过期和删除 API；资源管理不依赖 `task_id`。
- agent 通过 `service/object_store.S3ObjectStore`（boto3）访问 storage 服务，endpoint 由 `S3_ENDPOINT_URL` 配置，默认 `http://localhost:9000`。

## 问答运行时

`service/file_extraction_agent/application.stream_completion` 接收普通请求参数，负责业务校验、模型装配和资源预检；内部 `stream_execution(workspace, qa_model, messages, run_options)` 消费 `core.loop.run_qa_stream` 并生成类型化业务事件。路由只做协议适配，application/core 不依赖 protobuf 或 gRPC。

- 图使用 `QaState` 保存消息与重试状态，工具只接收本轮 workspace payload。
- 不同 RPC 不共享可变执行状态；`completion_id` 保留格式校验，但不用于注册、去重或取消。

```text
模型节点返回 AIMessage
  -> application 输出 model_message.started/delta/done、重试通知和 tool_started
  -> 工具节点并行执行，按共享 deadline 逐项经 custom 输出 ToolMessage，完整历史供下一轮模型使用
  -> 每项携带调用 ID、名称、参数和成功/失败结果
  -> application 输出 tool_completed / tool_failed，不维护 pending 配对字典
```

- 正常完成输出 `completion.completed`；普通执行异常输出 `completion.failed`；`CancelledError` / `GeneratorExit` 直接传播，不补发终态。
- 生成器逐层关闭，工具 `finally` 清理子进程。资源参数错误在首事件前返回 `INVALID_ARGUMENT`。

## 对外契约与迁移

- 文档服务接口：`DocumentResourceService.PrepareResources`，一次发送多个 `filename`/`bytes`，返回资源定位数组（`documents.zip` 归档，不再内联返回 HTML），默认监听 `127.0.0.1:8002`。
- agent 服务接口：`AgentService.ChatCompletion`，输入 `resource_refs`（`[{type, location}]`）+ `messages`，输出 `CompletionEvent` 服务端流，默认监听 `127.0.0.1:8001`。
- 采用标准 gRPC Health 探活，两服务各自注册 Health 名称；不提供问答查询或能力查询 RPC。
- 不再提供 FastAPI、HTTP 路由和 SSE；旧问答 `documents` 输入不保留。
- backend 分别通过两个 gRPC client 连接两服务；取消通过原 gRPC call 定位执行，无需按 completion ID 路由。
- 模型装配仅保存单一 provider 和调用方式，工具契约仅支持异步调用；取消沿 Task 传播，可见文本统一由 `messages.visible_text` 提取；已移除 DeepSeek 专用适配，统一使用标准 `ChatOpenAI`。
