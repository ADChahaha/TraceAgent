# 存储访问、请求内执行与取消边界

本页属 [文档问答执行设计](../DESIGN.md)，说明 workspace payload 存储边界、事件序列化校验与请求内取消语义。

## 事件结构与校验

- `schemas.CompletionEvent` 使用普通 dataclass，动态 `args`/`result` 保留原值；`Unset` 区分字段缺省与 JSON `null`，编码器保留显式零值和 `false`。
- `application` 使用 Pydantic `JsonValue` 校验嵌套动态值并拒绝非有限数值，不提前生成 JSON 字符串；路由在输出时只序列化一次。
- 请求级校验由 `application` 完成，`schemas` 只保留正在使用的消息、配置、资源引用与事件类型。

## 存储访问与 Workspace Payload

- prepare 子进程经 `service/object_store`（boto3，endpoint 由 `S3_ENDPOINT_URL` 配置，默认 `http://localhost:9000`）访问 storage 服务。
- `load_workspace_payload(resource_refs)` 按 `type` 解析 `documents` 与 `index` 的 `s3://<bucket>[/<key>]` 位置，拉取并校验 `documents.zip`、`manifest.json`、`index.json`、`vectors.npy`，序列化为 JSON payload（`documents_archive_b64` + `index`）。
- 父进程从不访问对象存储，也不持有 `ObjectStore`、`DocumentFileTree` 或 `EmbeddingResources`；父进程只保存 payload，并在每次工具调用时全量下发给一次性工具子进程。
- 只读工具子进程通过 `document_tree_from_payload(payload)` 从归档 bytes 重建 `ArchiveObjectStore` 与 `DocumentFileTree`，不访问 storage；索引的 `covered_files` 在 prepare 阶段已解析为 `documents/...` key。
- `grep` 在工具子进程中用纯 Python 遍历 `.md` 对象并做忽略大小写的字面匹配，不依赖 ripgrep。

## 请求内执行流

`application.stream_completion` 校验 `completion_id` 格式、非空 `messages` 与资源，调用 `build_qa_model` 后消费 `stream_execution`。路由只负责输入转换、输出编码、RPC 错误映射和取消传播；无 manager、运行时类、独立 producer、锁或队列，相同 `completion_id` 的 RPC 互不影响。

```text
handler 使用 aclosing 消费 application.stream_completion(...)
  -> application 预检资源、装配模型，调用 stream_execution(workspace, qa_model, messages, run_options)
  -> 输出 completion.created 与 source_indexed（仅 ok=true，不遍历文档）
  -> 直接 async for 消费 core.run_qa_stream，逐条分配 seq 并由路由编码 protobuf
  -> 正常结束输出 completion.completed；普通异常输出 completion.failed
```

- 暂停消费时外层不主动生产，由 gRPC 负责网络流控；图内部仍可并行运行工具，由 executor 清理未完成子任务。
- 首事件前参数错误映射 `INVALID_ARGUMENT`，其他初始化错误映射 `INTERNAL`。标准库与内部依赖顶部导入，重型 embedding 依赖延迟加载。

## 取消与进程边界

```text
客户端取消原 ChatCompletion call / deadline / 断连
  -> grpc.aio 取消 handler -> 当前 await 收到 CancelledError 并沿模型/图传播
  -> aclosing 逐层关闭 stream_completion 与内层生成器
  -> executor 清理未完成工具 Task；worker_client finally kill 工具与 prepare 子进程
  -> 执行退出，不交付取消终态
```

- 取消不撤回已交付事件或副作用，不强制中断同步代码，清理时间无固定保证；持久化状态与迟到写入拒绝由 backend 管理。
