# Backend API 设计

这份文档定义 backend 当前 QA-only API。backend 负责创建多文档 QA task、保存标准化文档、持久化多轮 messages/memory、消费 agent completion SSE，并向前端提供可续传事件流。

旧 `/tasks`、`/tasks/{id}/result`、`/tasks/{id}/trace`、`/tasks/{id}/replay` 和 `/tasks/{id}/audit` 已下线。

## 基本链路

```text
POST /qa/tasks 上传 PDF/DOCX
  -> backend 调 document_processor
  -> 保存 qa_documents
  -> 返回 ready task snapshot

POST /qa/tasks/{task_id}/inputs 提交问题
  -> 保存 user message
  -> 创建 turn
  -> 调 agent /v1/document-qa/chat/completions
  -> 保存 agent.event 和 assistant message
  -> terminal event 收口本轮 turn

GET /qa/tasks/{task_id}/events?after_seq=n
  -> 返回 seq > n 的持久化事件
  -> 当前没有 active turn 且事件已发完时关闭 SSE
```

## API 列表

```text
POST /qa/tasks
GET  /qa/tasks
GET  /qa/tasks/{task_id}

POST /qa/tasks/{task_id}/inputs
GET  /qa/tasks/{task_id}/events?after_seq=0
POST /qa/tasks/{task_id}/cancel

GET /capabilities
GET /healthz
```

内部 agent service API：

```text
POST /v1/document-processor/process
POST /v1/document-processor/docx/process
POST /v1/document-qa/chat/completions
POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

## `POST /qa/tasks`

创建一个 QA task，并同步完成文档标准化。

请求类型：`multipart/form-data`

字段：

- `files`：必填，上传的一个或多个 PDF/DOCX；multipart 中可以重复传入多个 `files` 字段。
- `file`：兼容单文件字段。
- `metadata`：可选 JSON object。

响应示例：

```json
{
  "task_id": "qa_task_xxx",
  "status": "ready",
  "stage": "ready",
  "error_message": null,
  "document_count": 1,
  "active_turn_id": null,
  "stream": {
    "state": "idle",
    "last_event_seq": 3
  }
}
```

处理步骤：

```text
multipart 请求
  -> 收集 files/file 上传项
  -> 在当前请求中读取 UploadFile bytes
  -> 校验至少一个文件和 PDF/DOCX 类型
  -> 写入 qa_tasks(status=processing, stage=document_processing)
  -> 写入 task.created
  -> 逐个调用 agent document_processor
       file_type=pdf  -> /v1/document-processor/process
       file_type=docx -> /v1/document-processor/docx/process
  -> 写入 qa_documents 和 document.processed
  -> 将 task 置为 ready/ready
  -> 写入 task.ready
  -> 返回 task snapshot
```

## `GET /qa/tasks`

查询最近 QA task 摘要。

查询参数：

- `limit`：可选，默认 `20`，后端限制在 `1..100`。

响应：

```json
{
  "tasks": [
    {
      "task_id": "qa_task_xxx",
      "status": "ready",
      "stage": "ready",
      "document_count": 2,
      "active_turn_id": null,
      "stream": {"state": "idle", "last_event_seq": 9}
    }
  ]
}
```

## `GET /qa/tasks/{task_id}`

返回单个 QA task detail。它复用 task snapshot 字段，并额外携带 evidence review 所需的只读文档视图。

处理步骤：

```text
task_id
  -> 读取 qa_tasks 生成 summary
  -> 读取 qa_documents 生成 documents(document_id, filename, display_html)
  -> 扫描 task 的 agent.event(source_indexed)，取最新 source_selectors
  -> 返回 summary + documents + source_selectors
```

响应会比 `GET /qa/tasks` 列表项多这些字段：

```json
{
  "documents": [
    {
      "document_id": "doc_xxx",
      "filename": "contract.pdf",
      "display_html": "<html>...</html>"
    }
  ],
  "source_selectors": {
    "0001.0001.0001": "p1"
  }
}
```

## `POST /qa/tasks/{task_id}/inputs`

向某个 QA task 提交一轮用户问题。

请求类型：`application/json`

字段：

- `content`：必填，用户问题。
- `run_options`：可选，透传给 agent completion，例如 `max_tool_calls`。

请求示例：

```json
{
  "content": "这份合同可以提前终止吗？",
  "run_options": {"max_tool_calls": 80}
}
```

处理步骤：

```text
content
  -> 校验 task 存在且没有 active turn
  -> 写入 qa_messages(role=user)
  -> 写入 qa_turns(status=queued)
  -> task.status=running, stage=answering, active_turn_id=turn_id
  -> 写入 message.created / turn.created / turn.started
  -> 组装 documents(filename + html)
  -> 组装 messages(user/assistant 历史 + 当前问题)
  -> 读取 memory_json
  -> 调 agent document QA completion stream
  -> 每条 agent SSE 写成 agent.event
  -> completion.completed 时保存最后一条非空 model_message 为 assistant message
  -> turn.completed，task 回到 ready/ready
```

响应示例：

```json
{
  "task_id": "qa_task_xxx",
  "turn_id": "turn_xxx",
  "status": "completed",
  "agent_completion_id": "cmp_xxx"
}
```

同一个 task 同时只能有一个 active turn；若已有 `queued / in_progress / cancelling` turn，返回 409。

## `GET /qa/tasks/{task_id}/events`

以 SSE 返回持久化事件，支持 `after_seq` 续传。

```text
GET /qa/tasks/{task_id}/events?after_seq=12
```

SSE data 示例：

```json
{
  "seq": 13,
  "task_id": "qa_task_xxx",
  "turn_id": "turn_xxx",
  "type": "agent.event",
  "status": "running",
  "stage": "answering",
  "payload": {
    "agent": "file_extraction_agent",
    "type": "model_message",
    "content": "可以提前终止。[证据](evidence://0001.0001.0001/S001)"
  },
  "created_at": "2026-05-23T00:00:00Z"
}
```

关闭语义：

```text
没有 active turn 且 seq > after_seq 的已有事件已经发送完
  -> 关闭 SSE

存在 active turn
  -> 等待新事件
```

## `POST /qa/tasks/{task_id}/cancel`

取消当前 active turn。

处理步骤：

```text
task_id
  -> 查找 active turn
  -> turn.status=cancelling
  -> 写入 turn.cancel_requested
  -> 立即写入 turn.cancelled 并清理 active_turn_id
  -> 如果已有 agent_completion_id，后台短超时 best-effort 调 agent cancel
```

响应：

```json
{
  "task_id": "qa_task_xxx",
  "turn_id": "turn_xxx",
  "status": "cancelled"
}
```

没有 active turn 时返回 409。

## `GET /capabilities`

返回当前后端能力：

```json
{
  "supported_file_types": ["pdf", "docx"],
  "task_types": [],
  "features": {
    "document_qa": true,
    "multi_turn": true,
    "event_stream": true,
    "cancel": true,
    "multiple_files": true
  }
}
```

## `GET /healthz`

用于本地启动检查和部署探活。该接口不访问 agent service，也不执行数据库读写，只确认 backend FastAPI 进程可响应请求。

处理链路：

```text
GET /healthz
  -> routes.capabilities.healthz()
  -> 返回 {"status": "ok"}
```
