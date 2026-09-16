# Document Service 设计

document service 是独立的文档资源生产服务，不导入 agent 的问答业务包。它接收会话级资源准备请求，完成解析、结构化、分块、embedding 和对象存储发布；backend 保存返回的 `ResourceRef`，agent 只消费这些引用。

## 资源契约

会话的物理资源落在一个固定桶 `res_<session_id>` 内，桶内 `raw/` 前缀对象是该会话文件的事实来源；`documents.zip`、`index/`、`manifest.json` 是由桶内 raw 全量重建的产物。`PrepareResources` 每次调用执行一次"增量合并 + 全量重建"：

```text
PrepareResources(session_id, files: filename + bytes, remove_raw: raw 引用)
  -> 校验 session_id，桶固定为 res_<session_id>
  -> 从桶内读回 raw/* 作为现有文件集（桶是事实来源，调用方无需传全量）
  -> 校验新文件（文件名非空且不含路径分隔符、内容非空）并按文件名覆盖合并
  -> 校验 remove_raw（type 必须为 raw、location 必须属于本会话桶），
     对桶内同名 raw delete_object，目标不存在则幂等跳过
  -> 剩余为空：删除 documents.zip、manifest.json、index/*，返回空引用
  -> 否则全批次类型校验（PDF/DOCX）后逐个解析
  -> document_processor.process：PDF -> MinerU HTML，DOCX -> python-docx HTML
  -> document_resources.publish_resources：HTML -> Markdown 文件树
  -> 使用缓存 embedder 分块并生成 index/index.json + vectors.npy
  -> 校验 manifest、向量维度和文档引用
  -> 通过 traceagent_shared.object_store 在同一桶内覆盖 documents.zip、index、manifest
  -> 返回 ResourceRef[]（documents/index + 全部剩余 raw）
```

上传与移除都返回重建后的全量引用；未变化的 raw 位置不变，backend 据此沿用旧尺寸并原子替换资源表。

服务入口为 [main.py](../main.py)，RPC 适配为 [routes.py](../routes.py)，共享协议位于仓库顶层 `agent_proto`。服务默认监听 `127.0.0.1:8002`，问答 agent 默认监听 `127.0.0.1:8001`；两者通过 storage 交接，不通过 Python import 交接。

## 边界

- `document_processor` 只负责单文件 PDF/DOCX -> HTML，不拥有资源发布。
- `document_resources.resources` 负责文档树构建、索引和 S3-compatible 发布到指定桶，不管理 raw 增删。
- `document_resources.application` 是会话层入口：维护桶内 raw 事实来源、应用上传与移除、驱动全量重建。
- `traceagent_shared` 只提供 ObjectStore/S3 语义，不理解 document 或 agent 业务。
- backend 负责 session、权限和资源引用；document service 不直接暴露用户 HTTP API。
- agent 只读取已发布资源，不重新解析或构建文档向量。

## 已知限制

- 全量重建会重新解析并重新 embedding 桶内全部 raw，单文件成本随会话文件数线性增长。
- 同一会话桶并发调用存在读改写竞争，依赖 backend 侧串行化。
- 构建或发布失败没有远端回滚；可能留下新写入的 raw 对象，会在下一次成功调用时随桶内容合并，自愈但短暂不一致。
