# Agent gRPC API

协议见 [agent.proto](../../agent_proto/agent.proto)。文档准备和问答属于两个独立 gRPC 服务，agent 的 HTTP 路由已移除，backend 通过两个独立 target 连接。

```text
DocumentResourceService.PrepareResources(files) -> 解析与索引构建 -> resource_path([{type, location}])
AgentService.ChatCompletion(resource_path + messages) -> 校验资源 -> 单轮执行 -> CompletionEvent 流
取消原 ChatCompletion call -> RPC 取消传播 -> handler 关闭本轮执行流
```

`resource_path` 为 `repeated ResourceRef`，每项 `{type, location}`，`location` 形如 `s3://<bucket>[/<key>]`。
`type` 取值：`documents`（`documents.zip` 归档，成员为 Markdown 文件树）、`index`（embedding 索引）、`raw`（原始上传文件，每文件一项）。资源发布在独立 `storage` 服务上。

## 主题文档

- [准备与请求](api/prepare-and-request.md)：Python 示例、`PrepareResources` 行为、`ChatCompletion` 请求字段
- [事件与重试](api/events-and-retry.md)：`CompletionEvent` 类型、动态 JSON、5 次退避与 `Retry-After`、消费端合并方式
- [取消与错误](api/cancellation-and-errors.md)：`call.cancel()` 传播链、Health 探活、错误码与超时说明

相关：[DESIGN.md](DESIGN.md) / [agent/README.md](../README.md)
