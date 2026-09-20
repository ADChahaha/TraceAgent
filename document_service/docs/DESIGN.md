# Document Service 设计

document service 是独立的文档资源生产服务，不导入 agent 的问答业务包。它接收会话级资源准备请求，完成解析、结构化、分块、embedding 和对象存储发布；backend 保存返回的 `ResourceRef`，agent 只消费这些引用。

## 资源契约

会话资源落在固定桶 `res_<session_id>`：`raw/` 保存原文件，`documents.zip`、`index/` 和 `manifest.json` 保存处理产物。上传只处理新批次，问答使用会话全量资源引用。

```text
PrepareResources(session_id, files, remove_raw)
  -> 校验会话、文件名和删除引用，只列 raw 名称
  -> 上传：只解析新增或替换文件，再构建该批次的 Markdown 和 embedding
  -> 沿用旧清单的模型和分块配置，保留未变文档的路径、分块及向量
  -> 合并新产物，排除替换或删除的旧文档，校验后发布会话归档与索引
  -> 发布成功后写新 raw、删目标 raw，返回全量 ResourceRef
  -> backend 更新 DB；每轮问答从 DB 取本 session 全部资源引用交给 agent
```

纯删除只裁剪已发布产物，不解析或调用模型；最后一个文件删除后清空产物。`main.run` 启动服务时在线程中加载默认 embedding 模型并执行一次短文本编码，完成后才监听并报告 SERVING；请求复用该进程缓存。模型预热失败会阻止服务就绪。`create_server` 的嵌入式测试入口默认不预热，生产 CLI 显式启用。

上传与移除都返回更新后的全量引用；未变化的 raw 位置不变，backend 据此沿用旧尺寸并原子替换资源表。

服务入口为 [main.py](../main.py)，RPC 适配为 [routes.py](../routes.py)，共享协议位于仓库顶层 `agent_proto`。服务默认监听 `127.0.0.1:8002`，问答 agent 默认监听 `127.0.0.1:8001`；两者通过 storage 交接，不通过 Python import 交接。

## 边界

- `document_processor` 只负责单文件 PDF/DOCX -> HTML，不拥有资源发布。
- `document_resources.resources` 负责文档树构建、索引、删除裁剪和 S3-compatible 发布到指定桶，不管理 raw 增删。
- `document_resources.application` 是会话层入口：维护桶内 raw 事实来源、应用上传与移除、驱动增量上传或纯删除裁剪。
- `traceagent_shared` 只提供 ObjectStore/S3 语义，不理解 document 或 agent 业务。
- backend 负责 session、权限和资源引用；document service 不直接暴露用户 HTTP API。
- agent 只读取已发布资源，不重新解析或构建文档向量。

## 已知限制

- 仍按会话归档合并发布，存在归档读写、压缩和索引读写成本；未改成每个文件独立资源包。
- 同一会话桶并发调用存在读改写竞争，依赖 backend 侧串行化。
- 解析、embedding 和本地校验失败不写桶。逐对象发布及其后的 raw 写入失败没有原子回滚，可能留下不一致；索引损坏时拒绝增量处理，不回退全量重建。

## 删除复用与兼容

manifest 新增 `document_roots`，将原文件名映射到文档一级目录。旧清单按 documents 原始顺序和三位数字前缀恢复映射，首次删除后保存映射；连续删除不重新编号。剩余 Markdown 路径、chunk_id、covered_files 及向量行保持不变，历史引用仍可定位。索引和映射无效时拒绝删除，不静默重算；校验全部在写桶之前，发布成功后才删除原文件。逐对象发布的中途故障仍不具备原子回滚。
