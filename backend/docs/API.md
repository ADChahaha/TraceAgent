# Backend API 设计

这份文档定义 `backend` 当前的 API。后端负责创建任务、保存任务状态、持久化事件、组织字段提交和审计记录；`agent service` 继续负责文档标准化和字段抽取，不直接写 backend 数据库。

当前设计把 API 分成三类：

```text
任务快照
  -> GET /tasks/{task_id}
  -> 回答任务现在是什么状态、是否已经结束、最后一条事件序号是多少

任务事件流
  -> GET /tasks/{task_id}/events
  -> 回答任务过程中发生了什么，支持全量回放和断线续传

业务读模型
  -> GET /tasks/{task_id}/result|trace|replay|audit
  -> 给结果页、回放页和审计页直接读取已经整理好的视图
```

## 基本链路

一次文档治理任务的主链路如下：

```text
前端上传一个或多个 PDF、task_type、task_spec 和 metadata
  -> POST /tasks 创建任务
  -> backend 生成 task_id，写入 task.created 事件
  -> POST /tasks 立即返回 task_id、pending/uploaded 和 stream.last_event_seq
  -> 前端打开 GET /tasks/{task_id}/events?after_seq=n 接收实时事件
  -> backend 后台逐个调用 document_processor，把上传文件转成 markdown/html/blocks
  -> backend 保存每个文件的标准化结果，不保存原始文件 bytes
  -> backend 将文档 html 和 task_spec 传给 file_extraction_agent
  -> backend 保存抽取结果和 trace，并把关键阶段归一成 task_events
  -> backend 对照 task_spec.fields 补齐 agent 没返回的字段，占位写成 failed/None
  -> backend 直接提交 resolved 字段，failed/None 字段保持未提交
  -> backend 保存最终结果和 audit
```

关键边界：

- `events` 是任务过程日志，用于实时 UI、回放和断线续传。
- `snapshot` 是任务当前状态，不返回完整 result、trace 或 replay。
- `result` 是最终字段结果。
- `trace` 是 agent 执行和证据细节。
- `replay` 是前端回放页读模型，可以由事件和 trace 重建，但保留独立接口能让页面刷新后直接读取。
- `audit` 是字段最终提交后的责任链路，覆盖 agent 自动提交和失败占位信息。

## API 列表

```text
POST /tasks
GET  /tasks
GET  /tasks/{task_id}
GET  /tasks/{task_id}/events
GET  /tasks/{task_id}/result
GET  /tasks/{task_id}/trace
GET  /tasks/{task_id}/replay
GET  /tasks/{task_id}/audit
GET  /capabilities
GET  /healthz
```

内部 agent service API：

```text
POST /v1/document-processor/process
POST /v1/file-extraction-agent/extract/stream
```

## 通用状态

任务业务状态 `status`：

```text
pending
processing
completed
failed
```

任务处理阶段 `stage`：

```text
uploaded
document_processing
extraction
done
```

事件流状态 `stream.state`：

```text
running
ended
```

`stream.state` 只描述事件流是否还会继续产生新事件；任务成功或失败仍然看 `status`。

## 事件模型

任务事件必须持久化，不能只放在内存里。每个事件使用任务内递增的 `seq` 作为续传游标。

推荐事件类型：

```text
task.created
task.stage_changed
document.processed
agent.event
field.written
task.completed
task.failed
```

`agent.event` 用于承载 agent service 的原始或归一化 stream 事件，例如 `tool_started`、`tool_completed`、`tool_failed`、`candidate_evidence_added`、`field_written` 和 `result_completed`。如果某类 agent 事件已经被 backend 提升成业务事件，例如字段写入，也可以同时写入 `field.written`，但前端要以 `seq` 去重。

## `POST /tasks`

创建一次文档治理任务。

请求类型：`multipart/form-data`

字段：

- `files`：必填，上传的一个或多个 PDF；multipart 中可以重复传入多个 `files` 字段。
- `file`：兼容旧版单文件字段；新前端应使用 `files`。
- `task_type`：必填，调用方定义的任务类型标识。
- `task_spec`：必填，显式字段 schema；后端不提供默认 task spec。
- `metadata`：可选，调用方透传的任务元信息。

请求示例：

```bash
curl -X POST "http://localhost:8000/tasks" \
  -F "files=@sample.pdf" \
  -F "files=@supplement.pdf" \
  -F "task_type=civilized_dormitory" \
  -F 'task_spec={"task_name":"civilized_dormitory","fields":[{"field_name":"room_numbers","display_name":"文明寝室房间号","type":"string","required":true,"critical":true}]}'
```

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "pending",
  "stage": "uploaded",
  "error_message": null,
  "stream": {
    "state": "running",
    "last_event_seq": 1
  }
}
```

处理步骤：

```text
multipart 请求
  -> 收集 files/file 上传项
  -> 在当前请求中读取 UploadFile bytes，避免后台任务开始前文件对象关闭
  -> 校验至少一个文件、文件类型、task_type 和 task_spec JSON object
  -> 写入 tasks，状态为 pending/uploaded
  -> 写入 task.created 事件，seq=1
  -> 返回 task_id、状态快照和 stream.last_event_seq
  -> 后台继续执行 document_processing / extraction
```

## `GET /tasks`

查询最近任务摘要列表，用于工作台恢复已有任务。

查询参数：

- `limit`：可选，默认 `20`，后端应限制在 `1..100`。

响应示例：

```json
{
  "tasks": [
    {
      "task_id": "task_xxx",
      "status": "completed",
      "stage": "done",
      "error_message": null,
      "has_result": true,
      "has_trace": true
    }
  ]
}
```

`GET /tasks` 只返回摘要，不返回完整字段结果、trace、replay 或审计明细。

## `GET /tasks/{task_id}`

返回任务当前快照：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "stage": "done",
  "error_message": null,
  "has_result": true,
  "has_trace": true,
  "stream": {
    "state": "ended",
    "last_event_seq": 8
  }
}
```

它不返回完整字段结果、trace、replay 或 audit commit。

## `GET /tasks/{task_id}/result`

返回最终字段结果：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "agent_value": "1-101,1-102",
      "final_value": "1-101,1-102",
      "field_status": "resolved",
      "source": "agent",
      "committed": true
    },
    {
      "field_name": "missing_required",
      "display_name": "缺失字段",
      "agent_value": null,
      "final_value": null,
      "field_status": "failed",
      "source": "none",
      "committed": false
    }
  ]
}
```

字段说明：

- `agent_value`：agent 抽取阶段的原始字段值。
- `final_value`：最终提交值；resolved 字段会与 agent_value 一致，failed/None 字段保持 `null`。
- `source`：`agent` 或 `none`。
- `committed`：是否已经写入 audit。

## `GET /tasks/{task_id}/trace`

返回抽取 trace 视图：

```text
documents + agent_runs + agent_stage_runs + field_traces
  -> 组装 document_processing / extraction 摘要步骤
```

trace 里只保留文档处理和字段抽取，不再包含 route validation 或人工审核。

## `GET /tasks/{task_id}/replay`

返回前端回放页需要的文档、展示 HTML、actions 和 result payload：

```text
documents + agent_runs + agent_stage_runs
  -> display_html
  -> outline_tree
  -> broad_plan
  -> actions
  -> result
```

## `GET /tasks/{task_id}/audit`

返回字段提交记录。每条 commit 只记录抽取结果和提交元数据，不再包含 route/review 字段。

## `GET /capabilities`

返回支持文件类型、任务类型和 feature flags。当前不暴露 route 或 review 决策列表。

## 事件续传

`GET /tasks/{task_id}/events?after_seq=n` 会从 `seq > n` 的事件开始继续返回。只要任务已经结束，`stream.state` 就会变成 `ended`。
