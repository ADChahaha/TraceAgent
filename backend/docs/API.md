# Backend API 设计

这份文档定义 `backend` 流式改造后的 API。后端负责创建任务、保存任务状态、持久化事件、组织人工复核、最终结果和审计记录；`agent service` 继续负责文档标准化、字段抽取和 route policy，不直接写 backend 数据库。

当前设计把 API 分成三类：

```text
任务快照
  -> GET /tasks/{task_id}
  -> 回答任务现在是什么状态、是否已经结束、最后一条事件序号是多少

任务事件流
  -> GET /tasks/{task_id}/events
  -> 回答任务过程中发生了什么，支持全量回放和断线续传

业务读模型
  -> GET /tasks/{task_id}/result|trace|replay|review|audit
  -> 给结果页、回放页、复核页和审计页直接读取已经整理好的视图
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
  -> backend 组装 field_outputs + refs_with_text + field_processes 调用 route_policy_agent
  -> backend 保存 accept/review/reject route 结果
  -> accept 字段进入 final result 和 audit
  -> review 字段生成 review handoff，等待 POST /tasks/{task_id}/review
  -> reject 或 failed 任务进入终态，并写入对应终止事件
```

关键边界：

- `events` 是任务过程日志，用于实时 UI、回放和断线续传。
- `snapshot` 是任务当前状态，不返回完整 result、trace 或 replay。
- `result` 是最终字段结果。
- `trace` 是 agent 执行和证据细节。
- `replay` 是前端回放页读模型，可以由事件和 trace 重建，但保留独立接口能让页面刷新后直接读取。
- `review` 是人工复核待办单和提交入口。
- `audit` 是字段最终提交后的责任链路，覆盖 agent 自动提交和人工 review 后提交。

## API 列表

```text
POST /tasks
GET  /tasks
GET  /tasks/{task_id}
GET  /tasks/{task_id}/events
GET  /tasks/{task_id}/result
GET  /tasks/{task_id}/trace
GET  /tasks/{task_id}/replay
GET  /tasks/{task_id}/review
POST /tasks/{task_id}/review
GET  /tasks/{task_id}/audit
GET  /capabilities
GET  /healthz
```

内部 agent service API：

```text
POST /v1/document-processor/process
POST /v1/file-extraction-agent/extract/stream
POST /v1/route-policy-agent/evaluate
```

## 通用状态

任务业务状态 `status`：

```text
pending
processing
waiting_review
completed
rejected
failed
```

任务处理阶段 `stage`：

```text
uploaded
document_processing
extraction
route_policy
review
field_commit
done
```

事件流状态 `stream.state`：

```text
running
ended
```

`stream.state` 只描述事件流是否还会继续产生新事件；任务成功、失败或拒绝仍然看 `status`。

route 决策 `route`：

```text
accept
review
reject
```

人工审核结论 `review_decision`：

```text
approve
revise_and_approve
reject
```

## 事件模型

任务事件必须持久化，不能只放在内存里。每个事件使用任务内递增的 `seq` 作为续传游标。

事件对象建议结构：

```json
{
  "seq": 13,
  "task_id": "task_xxx",
  "type": "field_written",
  "status": "processing",
  "stage": "extraction",
  "payload": {},
  "created_at": "2026-05-18T10:20:30Z"
}
```

字段说明：

- `seq`：同一个任务内从 1 开始递增，不能跳回。
- `type`：事件类型。
- `status` / `stage`：事件发生后的任务业务状态和阶段快照。
- `payload`：事件细节，按事件类型变化。
- `created_at`：事件写入时间，使用 UTC ISO 字符串。

推荐事件类型：

```text
task.created
task.stage_changed
document.processing_started
document.processed
agent.event
field.written
route_policy.started
route_policy.completed
review.required
task.completed
task.rejected
task.failed
```

`agent.event` 用于承载 agent service 的原始或归一化 stream 事件，例如 `tool_started`、`tool_completed`、`tool_failed`、`candidate_evidence_added`、`field_written` 和 `result_completed`。如果某类 agent 事件已经被 backend 提升成业务事件，例如字段写入，也可以同时写入 `field.written`，但前端要以 `seq` 去重。

第一阶段后端事件流已经持久化并通过 SSE 暴露；如果后端仍调用 agent service 的非流式抽取接口，就把抽取完成后的结果归一成 `agent.event`、`field.written` 和终态事件。后续切到 agent NDJSON stream 时，事件表和 `/events` 协议不需要改变，只需要把 agent 的逐条事件更早写入 `task_events`。

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
  -> 后台继续执行 document_processing / extraction / route_policy
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
      "status": "waiting_review",
      "stage": "review",
      "route": "review",
      "route_reason": "字段需要人工复核",
      "error_message": null,
      "has_result": true,
      "has_trace": true,
      "needs_review": true,
      "stream": {
        "state": "running",
        "last_event_seq": 42
      },
      "created_at": "2026-05-18T10:00:00Z",
      "updated_at": "2026-05-18T10:02:30Z"
    }
  ]
}
```

处理步骤：

```text
GET /tasks?limit=20
  -> 限制 limit 范围
  -> 按 updated_at DESC、created_at DESC、id DESC 读取最近任务
  -> 为每个任务补 status/stage/route/error_message/needs_review
  -> 查询每个任务最后一条事件 seq，填入 stream.last_event_seq
  -> 返回摘要列表
```

## `GET /tasks/{task_id}`

读取任务快照。这个接口用于初次打开任务页、断线恢复前校准状态、流结束后的最终确认，以及无流兜底轮询。

它不返回完整字段结果、trace、replay、review handoff 或 audit commit。

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "processing",
  "stage": "extraction",
  "route": null,
  "route_reason": null,
  "error_message": null,
  "has_result": false,
  "has_trace": true,
  "needs_review": false,
  "stream": {
    "state": "running",
    "last_event_seq": 18
  },
  "created_at": "2026-05-18T10:00:00Z",
  "updated_at": "2026-05-18T10:01:00Z"
}
```

处理步骤：

```text
task_id
  -> 读取 tasks 当前记录
  -> 读取 result/trace/review 是否已存在
  -> 读取 task_events 最大 seq
  -> 如果 status 是 completed/rejected/failed，stream.state=ended
  -> 否则 stream.state=running
  -> 返回轻量快照
```

## `GET /tasks/{task_id}/events`

读取任务事件流。这个接口是过程事件的唯一公开出口，支持全量回放和断线续传。

查询参数：

- `after_seq`：可选，默认 `0`。只返回 `seq > after_seq` 的事件。

响应类型：

```text
text/event-stream
```

SSE 消息示例：

```text
event: field.written
id: 13
data: {"seq":13,"task_id":"task_xxx","type":"field.written","status":"processing","stage":"extraction","payload":{"field_name":"room_numbers"},"created_at":"2026-05-18T10:01:15Z"}
```

处理步骤：

```text
GET /tasks/{task_id}/events?after_seq=n
  -> 校验 task_id 存在
  -> 从 task_events 读取 seq > n 的历史事件
  -> 按 seq 升序逐条发送
  -> 如果任务仍在 running，保持连接并继续发送新事件
  -> 如果任务已经 ended，补完历史事件后关闭连接
```

断线恢复规则：

```text
前端每收到一条事件
  -> 用 event.seq 更新本地 lastSeq
  -> 将 lastSeq 写入 localStorage 或 Electron 持久层

连接断开或页面刷新
  -> 先读取本地 lastSeq
  -> 如果没有本地 lastSeq，使用 0
  -> 可先 GET /tasks/{task_id} 校准任务 status 和 stream.last_event_seq
  -> 再 GET /tasks/{task_id}/events?after_seq=lastSeq
```

如果浏览器使用原生 `EventSource`，服务端也应设置 SSE `id: seq`。后端可以兼容 `Last-Event-ID` 请求头，但业务上仍建议显式支持 `after_seq`，方便刷新、跨窗口和 Electron 场景恢复。

## `GET /tasks/{task_id}/result`

查询最终字段结果。这个接口是结果页读模型，不承担过程回放。

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "route": "accept",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "field_type": "string",
      "agent_value": "1-101,1-102",
      "review_value": null,
      "final_value": "1-101,1-102",
      "field_status": "resolved",
      "route": "accept",
      "source": "agent",
      "committed": true
    }
  ]
}
```

字段说明：

- `agent_value`：Agent 原始定案值。
- `review_value`：人工修正值，未人工修正时为 `null`。
- `final_value`：最终展示或提交值。
- `source`：最终值来源，通常为 `agent` 或 `human`。
- `committed`：该字段是否已进入最终提交记录。

## `GET /tasks/{task_id}/trace`

查询 agent 执行层 trace 和证据，用于调试、论文展示和证据高亮。

响应主体建议包含：

```text
task_id
agent_status
failure_reason
steps[]
agent_trace[]
fields[]
metadata
```

处理步骤：

```text
task_id
  -> 读取 documents、agent_runs、agent_stage_runs、field_traces 和 field_routes
  -> 组装 document_processing / extraction / route_policy 摘要步骤
  -> 从字段 trace 派生 field_decisions 和 process_steps
  -> 返回 agent service 已暴露给 backend 的 trace 内容
```

`trace` 不保存也不伪造 agent service 未返回的 raw prompt、隐藏思考或 raw model response。

## `GET /tasks/{task_id}/replay`

查询前端回放页读模型。

`replay` 不是新的事实来源。它是把 `documents`、`trace.actions`、`result`、`field_states` 和 route 摘要整理成前端容易渲染的结构。前端如果已经完整消费 `events`，可以直接用事件流渲染实时回放；页面刷新或深链接进入时，`replay` 能避免从第一条事件重新聚合整个页面状态。

响应主体建议包含：

```text
task_id
status
stage
documents[]
display_html
outline_tree
actions[]
result
field_states
audit.route
audit.route_reason
```

## `GET /tasks/{task_id}/review`

获取人工复核待办单。只有任务处于 `waiting_review` 时才应调用。

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "waiting_review",
  "route": "review",
  "route_reason": "关键字段证据较弱，需要人工确认",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "field_type": "string",
      "agent_value": "1-101,1-102",
      "field_status": "resolved",
      "needs_review": true,
      "review_reason": "字段由候选证据定案，需要人工确认",
      "evidence_texts": ["1-101、1-102 被列为文明寝室"],
      "evidence_refs": [
        {
          "document_id": "doc_xxx",
          "page": 2,
          "block_id": "doc_xxx:p2:b3"
        }
      ],
      "related_fields": [],
      "actions": ["tree", "read", "write_field"],
      "reason": "候选证据支持字段值",
      "failure_reason": null,
      "agent_process": {}
    }
  ]
}
```

处理步骤：

```text
task_id
  -> 校验任务 status 必须是 waiting_review
  -> 读取 extracted_fields、field_traces 和 needs_review=true 的 field_routes
  -> 合并 agent_value、证据、route_reason、related_fields 和 agent_process
  -> 返回人工可编辑的 handoff 包
```

## `POST /tasks/{task_id}/review`

提交人工复核结果。

请求示例：

```json
{
  "decision": "revise_and_approve",
  "fields": [
    {
      "field_name": "room_numbers",
      "review_value": "1-101,1-102,1-103",
      "comment": "人工根据原文补充遗漏房间"
    }
  ],
  "comment": "复核完成",
  "reviewer": "operator"
}
```

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "stage": "done",
  "review_decision": "revise_and_approve"
}
```

处理步骤：

```text
人工提交 decision、字段修正值和备注
  -> 校验任务必须处于 waiting_review
  -> 写入 reviews 和 review_fields
  -> approve 沿用 agent_value 作为 final_value
  -> revise_and_approve 使用 review_value 作为 final_value
  -> reject 将任务置为 rejected，不生成字段提交
  -> 对通过的字段写入 field_commits
  -> 写入 task.completed 或 task.rejected 事件
  -> 返回更新后的任务状态
```

## `GET /tasks/{task_id}/audit`

查询字段级最终提交与责任链路。`audit` 用于回答“最终值是谁在什么时候、基于什么 route 和证据提交的”，不是全过程事件日志。

响应示例：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "field_commits": [
    {
      "field_name": "room_numbers",
      "final_value": "1-101,1-102,1-103",
      "route": "review",
      "reviewed": true,
      "review_decision": "revise_and_approve",
      "agent_value": "1-101,1-102",
      "review_value": "1-101,1-102,1-103",
      "evidence_refs": [
        {
          "document_id": "doc_xxx",
          "page": 2,
          "block_id": "doc_xxx:p2:b3"
        }
      ],
      "used_global_lookup": false,
      "used_validation_rule": false,
      "action_types": ["tree", "read", "write_field"],
      "related_fields": [],
      "committed_by": "human",
      "committed_at": "2026-05-18T10:05:00Z",
      "agent_process": {}
    }
  ]
}
```

## `GET /capabilities`

查询系统能力边界，供前端上传页和实验脚本使用。

响应示例：

```json
{
  "supported_file_types": ["pdf"],
  "task_types": [],
  "routes": ["accept", "review", "reject"],
  "review_decisions": ["approve", "revise_and_approve", "reject"],
  "features": {
    "trace": true,
    "review": true,
    "audit": true,
    "stream": true,
    "external_task_spec": true,
    "multiple_files": true
  }
}
```

## `GET /healthz`

健康检查。

响应示例：

```json
{
  "status": "ok"
}
```

## 错误语义

第一版保持简单：

- 请求体或文件缺失：`422`
- 文件类型不支持、`task_spec` 缺失或 JSON 非法：`422`
- `task_id` 不存在：`404`
- 当前任务状态不允许执行该操作：`409`
- agent HTTP 调用或后端流程异常：`502`

如果任务已经创建，后台流程失败时应：

```text
异常
  -> 写 task.failed 事件
  -> 更新 tasks.status=failed
  -> 更新 tasks.stage=done
  -> 写 error_message
  -> stream.state 变为 ended
```

`POST /tasks` 只保证任务已创建并入队；后台失败原因以后续 `GET /tasks/{task_id}` 中的 `error_message` 和 `events` 中的 `task.failed` 为准。

## 前端推荐流程

新建任务：

```text
POST /tasks
  -> 得到 task_id 和 stream.last_event_seq
  -> GET /tasks/{task_id}/events?after_seq=stream.last_event_seq
  -> 实时渲染事件
  -> 任务进入 completed/waiting_review/rejected/failed 后关闭或等待服务端关闭流
```

打开已有任务：

```text
GET /tasks/{task_id}
  -> 渲染 status/stage/route/error_message
  -> 从本地读取 lastSeq；没有就用 0
  -> GET /tasks/{task_id}/events?after_seq=lastSeq
  -> 如果 status 已经是终态，也可以直接读取 result/replay/review/audit
```

断线恢复：

```text
EventSource 或 fetch stream 断开
  -> 保留最后处理成功的 seq
  -> GET /tasks/{task_id} 校准当前 status 和 stream.last_event_seq
  -> GET /tasks/{task_id}/events?after_seq=lastSeq
  -> 后端补发断线期间已落库的事件
```

页面刷新：

```text
刷新后 JS 内存丢失
  -> 从 localStorage 或 Electron 持久层读取 lastSeq
  -> 没有 lastSeq 就 after_seq=0 全量回放
  -> 有 lastSeq 就 after_seq=lastSeq 增量续传
```
