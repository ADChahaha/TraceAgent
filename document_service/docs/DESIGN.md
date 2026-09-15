# Document Service 设计

document service 是独立的文档资源生产服务，不导入 agent 的问答业务包。它接收上传文件，完成解析、结构化、分块、embedding 和对象存储发布；backend 保存返回的 `ResourceRef`，agent 只消费这些引用。

```text
PrepareResources(files: filename + bytes)
  -> 校验空批次、文件名和 PDF/DOCX 类型
  -> document_processor.process：PDF -> MinerU HTML，DOCX -> python-docx HTML
  -> document_resources.prepare_resources：HTML -> Markdown 文件树
  -> 使用缓存 embedder 分块并生成 index/index.json + vectors.npy
  -> 校验 manifest、向量维度和文档引用
  -> 通过 traceagent_shared.object_store 发布 documents.zip、index、manifest、raw
  -> 返回 ResourceRef[]
```

服务入口为 [main.py](../main.py)，RPC 适配为 [routes.py](../routes.py)，共享协议位于仓库顶层 `agent_proto`。服务默认监听 `127.0.0.1:8002`，问答 agent 默认监听 `127.0.0.1:8001`；两者通过 storage 交接，不通过 Python import 交接。

## 边界

- `document_processor` 只负责单文件 PDF/DOCX -> HTML，不拥有资源发布。
- `document_resources` 负责 HTML -> 文档树、索引和 S3-compatible 发布。
- `traceagent_shared` 只提供 ObjectStore/S3 语义，不理解 document 或 agent 业务。
- backend 负责 session、权限和资源引用；document service 不直接暴露用户 HTTP API。
- agent 只读取已发布资源，不重新解析或构建文档向量。
