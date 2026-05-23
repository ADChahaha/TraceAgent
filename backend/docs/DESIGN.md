# Backend Design

这份文档是 `backend` 的设计入口。当前 backend 已破坏式重构为 QA-only：它不再执行字段抽取、字段提交、审计或 replay 组装，而是负责多文档 QA task 的文档保存、多轮消息状态、agent completion 事件持久化和取消。

接口细节见 [API.md](API.md)。

## 1. 目标与边界

backend 是多轮 QA 的持久化事实来源：

```text
上传 PDF
  -> backend 调 agent document_processor
  -> backend 保存 qa_documents

用户提问
  -> backend 保存 user message
  -> backend 把 documents + messages + memory 传给 agent completion
  -> backend 保存 agent model_message / tool events / terminal events
  -> backend 保存 assistant message，供下一轮上下文使用
```

职责边界：

- `backend` 管理 QA task、documents、messages、turns、events 和 memory。
- `agent service` 负责 PDF 标准化和单次 document QA completion。
- `backend` 通过 HTTP 调用 `agent service`，不 import `agent/` 内部包。
- `backend` 不持久化上传原始文件 bytes；只保存 document_processor 输出的 HTML/Markdown/blocks。
- `backend` 不内置业务 schema，也不接收 `task_spec`。
- `POST /qa/tasks` 和 `POST /qa/tasks/{task_id}/inputs` 都只写入任务/turn 状态后立刻返回；耗时的 document processing 和 agent completion 在 backend 后台线程里继续执行。

## 2. 项目结构

```text
backend/
  main.py
  core/
    config.py
    db.py
    storage.py
  routes/
    tasks.py
    capabilities.py
    errors.py
  crud/
    qa_tasks.py
    json_utils.py
  services/
    task_service.py
    agent_client.py
    errors.py
    time_utils.py
  models/
    schema.py
  tests/
    test_qa_task_flow.py
    test_config.py
    docs/
  docs/
    API.md
    DESIGN.md
    DEVLOG.md
```

模块边界：

- `main.py` 初始化 SQLite、agent client 和 `QaTaskService`，挂载 routes。
- `routes/tasks.py` 只做 HTTP 参数解析、SSE 序列化和错误映射。
- `routes/capabilities.py` 提供 `/capabilities` 能力声明和 `/healthz` 轻量进程探活。
- `services/task_service.py` 编排 QA task 创建、输入、agent completion、事件写入和取消。
- `GET /qa/tasks/{task_id}` 是详情读模型：在 summary 之外返回 `qa_documents.display_html` 和最新 `source_indexed.source_selectors`，供前端 evidence link 打开右侧原文。
- `services/agent_client.py` 封装 agent service HTTP 调用。
- `crud/qa_tasks.py` 封装 QA 表读写，不做业务决策。
- `models/schema.py` 定义 QA-only SQLite schema。

## 3. 数据流

创建 QA task：

```text
POST /qa/tasks multipart(files/file, metadata)
  -> routes.tasks 读取每个 UploadFile bytes
  -> QaTaskService 校验至少一个 PDF
  -> 先校验每个 filename 能推断为支持的 file_type
  -> qa_tasks 插入 processing/document_processing
  -> qa_events 写 task.created
  -> 启动后台线程 _process_task_documents(task_id, files)
  -> 立刻返回 processing/document_processing task snapshot

后台文档线程
  -> 逐个 AgentClient.process_document(...) 调 agent /v1/document-processor/process
  -> qa_documents 保存 filename/html/display_html/markdown/md_list/blocks/meta/warnings
  -> 每份文档写 document.processed
  -> 如果已有 active turn，把 task 更新为 running/answering；否则更新为 ready/ready
  -> 写 task.ready
  -> 如果文档处理失败，写 task.failed；已有 active turn 时同时写 turn.failed
```

提交用户输入：

```text
POST /qa/tasks/{task_id}/inputs
  -> 校验 task 存在
  -> qa_turns 中不能已有 queued/in_progress/cancelling turn
  -> qa_messages 写 role=user
  -> qa_turns 写 queued
  -> qa_tasks 写 running/answering 或 running/document_processing + active_turn_id
  -> qa_events 写 message.created / turn.created
  -> 启动后台线程 _run_turn_when_ready(task_id, turn_id)
  -> 立刻返回 queued turn snapshot

后台 QA 线程
  -> 如果 task 仍是 document_processing，就轮询等待文档处理完成
  -> 如果 turn 已 cancelling/cancelled/failed，则直接收口
  -> qa_events 写 turn.started
  -> 组装 documents: qa_documents(filename + html)
  -> 组装 messages: qa_messages(role + content)
  -> 组装 memory: qa_tasks.memory_json
  -> AgentClient.create_document_qa_completion_stream(...)
  -> 每条 agent SSE 写 qa_events(agent.event)
  -> completion.completed 时，把最后一条非空 model_message 写成 role=assistant
  -> qa_turns 写 completed
  -> qa_tasks 写 ready/ready 并清空 active_turn_id
  -> qa_events 写 turn.completed
```

取消：

```text
POST /qa/tasks/{task_id}/cancel
  -> 查找 active turn
  -> qa_turns 写 cancelling
  -> 如果 turn.agent_completion_id 已有值，调用 agent cancel endpoint
  -> qa_events 写 turn.cancel_requested
  -> 如果 completion 还没开始，立即写 turn.cancelled 并清空 active_turn_id
  -> 如果 completion 已开始，后台 QA 线程在事件边界观察 cancelling 并写 turn.cancelled
```

事件续传：

```text
GET /qa/tasks/{task_id}/events?after_seq=n
  -> 读取 qa_events 中 sequence > n 的事件
  -> 每条事件用 SSE 输出 event/id/data
  -> 如果没有 active turn 且已发完当前事件，关闭 SSE
  -> 如果还有 active turn，轮询等待新事件
```

详情读取：

```text
GET /qa/tasks/{task_id}
  -> serialize_task(task)
  -> qa_documents 取 document_id / filename / display_html
  -> qa_events 里按顺序扫描 agent.event(source_indexed)
  -> 取最新 source_selectors(path_id -> display_html DOM id)
  -> 返回给前端用于 evidence review
```

## 4. 数据表

QA-only schema：

```text
qa_tasks
  -> id, status, stage, metadata_json, memory_json, active_turn_id, error_message, timestamps

qa_documents
  -> task_id, filename, file_type, html, display_html, markdown, md_list_json, blocks_json, processor_meta_json, warnings_json

qa_messages
  -> task_id, turn_id, role(user/assistant/system), content, metadata_json, created_at

qa_turns
  -> task_id, status(queued/in_progress/cancelling/completed/cancelled/failed), agent_completion_id, user_message_id, error_message, timestamps

qa_events
  -> task_id, turn_id, sequence, event_type, status, stage, payload_json, created_at
```

旧字段抽取表 `tasks/documents/agent_runs/agent_stage_runs/extracted_fields/field_traces/field_commits/task_events` 会在初始化时删除。当前分支不做旧库迁移兼容。

## 5. 状态模型

task status：

```text
processing
ready
running
failed
```

task stage：

```text
document_processing
ready
answering
done
```

turn status：

```text
queued
in_progress
cancelling
completed
cancelled
failed
```

stream state：

```text
idle
running
```

`stream.state` 只说明当前是否还有 active turn；历史事件永远通过 `after_seq` 续传。

## 6. Agent Client

`AgentClient` 只调用三个 agent service API：

```text
process_document(...)
  -> POST /v1/document-processor/process

create_document_qa_completion_stream(...)
  -> POST /v1/document-qa/chat/completions
  -> 解析 text/event-stream 中的 data JSON

cancel_document_qa_completion(completion_id)
  -> POST /v1/document-qa/chat/completions/{completion_id}/cancel
```

backend 不读取 agent 内存状态，不保存 agent runtime，只保存 agent 通过 SSE 发出的事件。

## 7. 已删除部分

当前实现不再包含：

- 旧 `/tasks` 字段抽取 API。
- `task_spec` 输入。
- `result/trace/replay/audit` 字段结果读模型。
- 字段提交和人工审核。
- route policy 相关流程。
