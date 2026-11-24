# Agent Service Design

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

## 主题文档

- [模块边界](design/modules.md)：22 个核心文件职责与 storage 交接方式
- [传输与部署](design/deployment.md)：`grpc.aio` 启停、64 MiB 消息上限、共享协议 wheel 与取消传播
- [资源与运行时](design/lifecycle-and-runtime.md)：`res_*` 桶结构、问答运行时流、gRPC 接口与迁移变化

相关：[API.md](API.md) / [问答内核设计](../service/file_extraction_agent/docs/DESIGN.md) / [问答内核决策](../service/file_extraction_agent/docs/DECISIONS.md) / [文档资源设计](../../document_service/document_resources/docs/DESIGN.md)
