# Document Service

document service 独立负责上传文件的解析、文档树生成、embedding 索引构建和资源发布。
它不导入问答 agent；问答服务只通过共享协议接收资源定位，并经 shared object store 从 storage 读取。

```text
PrepareResources(filename + bytes)
  -> PDF MinerU / DOCX python-docx
  -> HTML -> Markdown 文件树
  -> embedding index + manifest
  -> traceagent_shared.object_store 发布 raw/documents/index
  -> ResourceRef[]
```

从仓库根目录启动：

```bash
conda activate agent-gate
python -m document_service.main --host 127.0.0.1 --port 8002
```

服务使用 `DOCUMENT_HOST`、`DOCUMENT_PORT`、`DOCUMENT_GRPC_WORKERS`、
`DOCUMENT_GRPC_MAX_MESSAGE_BYTES` 和 `S3_ENDPOINT_URL` 配置。
