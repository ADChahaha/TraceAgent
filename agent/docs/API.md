# Agent Service API

先上传一组 PDF / DOCX，准备完成后保存返回的资源路径；每轮问答只回传路径及完整历史 messages。

```text
files → POST /v1/document-resources → resource_path + documents
resource_path + messages → POST /v1/document-qa/chat/completions → SSE
```

两个接口部署在同一个 agent 服务中，共用本机资源目录。backend 无需访问 agent 磁盘。**当前 backend 尚未切换到下面的新契约。**

## 文档解析与资源准备

```http
POST /v1/document-resources
Content-Type: multipart/form-data
```

重复使用 `files` 字段上传一个或多个 PDF / DOCX；文件类型由后缀判断，不接收 task_id。同步等待全部文件解析、文件树生成、分块及文档 embedding 完成。

```bash
curl -X POST http://127.0.0.1:8001/v1/document-resources \
  -F "files=@contract.pdf" -F "files=@appendix.docx"
```

成功返回 200：

```json
{
  "resource_path": "D:/TraceAgent/agent/data/resources/res_abc",
  "documents": [
    {"filename": "contract.pdf", "html": "<html>...</html>"},
    {"filename": "appendix.docx", "html": "<html>...</html>"}
  ]
}
```

HTML 用于原文展示；路径用于后续问答。资源发布后不会被 completion 清理，首版没有删除接口或自动过期。

- 缺少文件、后缀不支持等输入错误：422。
- 解析或资源准备失败：500，detail 标明阶段或文件及原因；不返回可用路径。
- 任一文件失败则整组失败。调用方的 HTTP 超时需覆盖 OCR 和 embedding 的准备耗时。

## 路径问答

```http
POST /v1/document-qa/chat/completions
Content-Type: application/json
Accept: text/event-stream
```

```json
{
  "completion_id": "cmp_123",
  "resource_path": "D:/TraceAgent/agent/data/resources/res_abc",
  "messages": [{"role": "user", "content": "付款条件是什么？"}],
  "run_options": {"tool_execution_timeout": 60},
  "model_config": {
    "base_url": "https://example.com/v1",
    "api_key": "...",
    "model_name": "model",
    "api_transport": "responses"
  }
}
```

- completion_id 必填，1–128 位，以字母或数字开头，其余允许字母、数字、下划线和短横线；活动 ID 不可重复。
- resource_path 必须是本服务受管理目录下的已发布完整资源，不能传任意本机目录。
- messages 非空，支持 OpenAI 风格 user / assistant / tool 历史；assistant 可携带 tool_calls，tool 必须携带 tool_call_id。不自动摘要或裁剪。
- 模型配置可省略，沿用环境配置；api_transport 支持 responses / chat_completions。
- 不再接收 documents、metadata.task_id 或 workspace_root。stream 保留兼容字段，当前仍始终返回 SSE。
- 资源缺失、损坏、引用越界、清单版本不支持等在流开始前返回 422，不自动重建。

SSE 按 seq 从 1 递增：

```text
event: completion.created
data: {"id":"cmp_123","type":"completion.created","status":"in_progress","seq":1}
```

| 事件 | 含义 |
| --- | --- |
| completion.created | 开始执行 |
| source_indexed | 当前资源 documents 目录的 workspace_root 与 tree |
| model_message | 可见正文、tool_calls、is_final 和可选 stop_signal |
| tool_started | 已发布的工具调用 ID、名称与参数 |
| tool_completed / tool_failed | 对应调用的结果 |
| completion.completed / completion.cancelled / completion.failed | 唯一终态 |

最终回答由 is_final=true 标记，在结论句后引用真实 Markdown 路径。取消已发布工具批次时，先配齐结果再结束。

## 取消与查询

```http
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

返回 `{"id":"cmp_123","status":"cancelling"}`；未找到活动 completion 时返回 not_found。已取消或结束的 completion 不会删除文档资源。

`GET /v1/document-qa/chat/completions/{completion_id}` 仍返回 `{"status":"not_implemented"}`。

`GET /healthz` 返回 `{"status":"ok"}`；`GET /v1/ocr/capabilities` 返回 PDF / DOCX 支持情况。

## 部署配置

- `DOCUMENT_RESOURCES_ROOT`：持久资源根目录。
- `EMBEDDING_MODEL`、`EMBEDDING_BACKEND`、`EMBEDDING_CHUNK_SIZE`、`EMBEDDING_CHUNK_OVERLAP`：准备阶段配置；查询使用资源清单记录的配置。
- `BASE_URL`、`OPENAI_API_KEY`、`MODEL`、`MODEL_API_TRANSPORT`：问答模型配置。
- `MINERU_BIN`、`DOCUMENT_PROCESSOR_MINERU_LANG`：PDF 解析配置。

旧 `/v1/document-processor/process`、专用 DOCX 路由和旧 OCR process 路由不再提供。
