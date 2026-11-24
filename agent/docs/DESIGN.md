# Agent Service Design

> backend 负责会话和事件持久化；document service 与 agent service 保持独立部署，通过 storage 交接资源。

文档资源准备和问答执行是两个可独立部署的 gRPC 服务。document service 负责把上传文件转换为可复用资源并发布到 storage；agent service 只读取资源并执行一次问答。多轮会话、任务与事件持久化由 backend 管理。

```text
DocumentResourceService.PrepareResources(files)
  -> document_processor -> document_resources -> storage (res_*)
  -> 返回 resource_refs([{type, location}])

AgentService.ChatCompletion(resource_refs + messages)
  -> application.stream_completion 校验并 prepare_workspace
  -> 经 S3ObjectStore 从 storage 读取资源并执行 LangGraph 问答循环
  -> application.stream_execution 生成带 seq 的 CompletionEvent -> gRPC 流
```

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 模块边界与服务解耦 | [design/modules.md](design/modules.md) | 22 个核心文件职责表与 document/agent 经 storage 交接边界 |
| 传输、部署与取消 | [design/deployment.md](design/deployment.md) | grpc.aio 启停、64 MiB 上限、共享协议 wheel、安装启动与取消传播 |
| 资源生命周期、问答与契约 | [design/lifecycle-and-runtime.md](design/lifecycle-and-runtime.md) | `res_*` 桶结构、问答运行时流、对外 gRPC 契约与迁移说明 |

## 相关入口

- 接口示例与字段规范：[API.md](API.md)
- 问答内核详细设计：[file_extraction_agent/docs/DESIGN.md](../service/file_extraction_agent/docs/DESIGN.md)
- 文档资源设计：[document_resources/docs/DESIGN.md](../../document_service/document_resources/docs/DESIGN.md)
