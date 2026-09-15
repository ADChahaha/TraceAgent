# Document Service API

服务名为 `traceagent.v1.DocumentResourceService`，共享协议见 [agent.proto](../../agent_proto/agent.proto)。

## PrepareResources

```text
PrepareResources(files, session_id, remove_raw)
  -> 校验批次和文件类型
  -> 解析 PDF/DOCX
  -> 构建 Markdown 文件树和 embedding index
  -> 发布到 storage
  -> 返回 repeated ResourceRef
```

默认 gRPC 地址为 `127.0.0.1:8002`。标准 Health 服务名为
`traceagent.v1.DocumentResourceService`。

资源准备失败不会返回部分可用引用；问答 agent 通过 `ResourceRef` 读取已发布的 documents/index/raw 对象。
