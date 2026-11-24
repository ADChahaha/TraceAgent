# Agent gRPC API

协议见 [agent.proto](../../agent_proto/agent.proto)。文档准备和问答属于两个独立 gRPC 服务，agent 的 HTTP 路由已移除，backend 通过两个独立 target 连接。

```text
DocumentResourceService.PrepareResources(files) -> 解析与索引构建 -> resource_path([{type, location}])
AgentService.ChatCompletion(resource_path + messages) -> 校验资源 -> 单轮执行 -> CompletionEvent 流
取消原 ChatCompletion call -> RPC 取消传播 -> handler 关闭本轮执行流
```

`resource_path` 为 `repeated ResourceRef`，每项 `{type, location}`，`location` 形如 `s3://<bucket>[/<key>]`。
`type` 取值：`documents`（`documents.zip` 归档，成员为 Markdown 文件树）、`index`（embedding 索引）、`raw`（原始上传文件，每文件一项）。资源发布在独立 `storage` 服务上。

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 资源准备与问答请求 | [api/prepare-and-request.md](api/prepare-and-request.md) | Python 调用示例、`PrepareResources` 契约、`ChatCompletion` 请求字段校验 |
| 事件流与重试规则 | [api/events-and-retry.md](api/events-and-retry.md) | `CompletionEvent` 类型表、JSON 动态字段、5 次退避与 `Retry-After`、消费端合并规则 |
| 取消、探活与错误码 | [api/cancellation-and-errors.md](api/cancellation-and-errors.md) | `call.cancel()` 传播链、Health 探活、gRPC 错误映射表与 deadline 约定 |

## 相关入口

- 架构设计：[DESIGN.md](DESIGN.md)
- 部署参数与协议生成命令：[agent/README.md](../README.md)
