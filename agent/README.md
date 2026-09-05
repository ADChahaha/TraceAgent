# Agent Service

agent 提供文档准备与路径问答两个 HTTP 入口。文档准备将 PDF / DOCX 解析成 HTML，并生成可跨轮复用的 Markdown 文件树与 embedding 索引；问答读取资源路径并通过 SSE 输出回答。

```text
上传 files → POST /v1/document-resources → resource_path + documents（filename/html）
提交 resource_path + messages → POST /v1/document-qa/chat/completions → SSE
```

两个入口部署在同一个 agent 服务中，共用本机资源目录。backend 保存、回传路径，无需读取 agent 磁盘。本次只改 agent，backend 仍需后续适配新接口。

## 启动

```bash
conda activate agent-gate
pip install -e ".[dev,embeddings]"
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

准备阶段必须安装 embedding 依赖；PDF 需要 MinerU，DOCX 使用 python-docx。默认 embedding 后端为 OpenVINO。

启动前配置问答模型的 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`，可选 `MODEL_API_TRANSPORT=responses` 或 `chat_completions`。PDF 语言使用 `DOCUMENT_PROCESSOR_MINERU_LANG`（默认 japan，中文可设 ch）。

资源目录由 `DOCUMENT_RESOURCES_ROOT` 配置，默认 `agent/data/resources`。`EMBEDDING_MODEL`、`EMBEDDING_BACKEND`、分块参数在准备阶段记录到资源清单；查询沿用记录的模型配置。资源不会随问答结束删除，首版无自动过期或删除接口。

completion cancel 依赖进程内注册表，使用单 worker。启动后 `GET /healthz` 探活，`GET /docs` 查看 OpenAPI。

## 模块

| 目录 | 职责 |
| --- | --- |
| routes | HTTP 校验、线程池调度和错误映射 |
| service/document_processor | PDF / DOCX → HTML |
| service/document_resources | HTML → 文档树、embedding 索引、资源清单；路径加载 |
| service/file_extraction_agent | 路径问答、模型/工具循环、事件和取消管理 |

问答工具为 ls / grep / read / search_embedding。模型引用 documents 目录下真实 Markdown 路径，最终回答以 is_final=true 标记。agent 不存储多轮会话或 backend 数据库。

## 文档与验证

- [HTTP API](docs/API.md)：上传和问答请求示例、响应与错误。
- [服务设计](docs/DESIGN.md)：模块边界和生命周期。
- [资源设计](service/document_resources/docs/DESIGN.md)：本地资源准备与加载。
- [问答设计](service/file_extraction_agent/docs/DESIGN.md)：批次消息、工具与取消。

```bash
conda activate agent-gate
python -m pytest tests -q
```

测试包含真实 DOCX 解析、替身 embedding、路径复用、取消竞态及 wheel 安装包内容验证；不依赖真实 provider 或下载 embedding 模型。
