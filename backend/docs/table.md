# Backend 数据表

## qa_tasks

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | QA task id。 |
| `status` | `TEXT NOT NULL` | task 粗粒度状态，例如 `processing`、`ready`、`running`、`failed`。 |
| `stage` | `TEXT NOT NULL` | task 当前阶段，例如 `document_processing`、`ready`、`answering`。 |
| `metadata_json` | `TEXT NOT NULL` | 创建 task 时传入的 metadata JSON。当前不参与核心流程判断。 |
| `active_turn_id` | `TEXT` | 当前活跃 turn 的辅助索引。不是数据库锁，也不是唯一并发事实来源。 |
| `error_message` | `TEXT` | task 失败时的错误信息。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |
| `updated_at` | `TEXT NOT NULL` | 最近更新时间。 |

## qa_documents

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 文档记录 id。 |
| `task_id` | `TEXT NOT NULL` | 所属 task，外键指向 `qa_tasks(id)`。 |
| `filename` | `TEXT NOT NULL` | 上传文件名。 |
| `file_type` | `TEXT NOT NULL` | 推断出的文件类型，例如 `pdf`、`docx`。 |
| `content_type` | `TEXT` | 上传时的 MIME content type。 |
| `upload_size_bytes` | `INTEGER NOT NULL` | 上传文件大小。 |
| `upload_sha256` | `TEXT NOT NULL` | 上传文件内容 SHA-256。 |
| `html` | `TEXT NOT NULL` | agent document_processor 产出的标准 HTML，供 QA completion 使用。 |
| `display_html` | `TEXT NOT NULL` | 供前端 evidence review 展示的 HTML。 |
| `markdown` | `TEXT NOT NULL` | 文档 Markdown 表达。 |
| `md_list_json` | `TEXT NOT NULL` | Markdown list 结构 JSON。 |
| `blocks_json` | `TEXT NOT NULL` | 文档 block 结构 JSON。 |
| `processor_meta_json` | `TEXT NOT NULL` | document_processor 元信息 JSON。 |
| `warnings_json` | `TEXT NOT NULL` | 文档处理 warning JSON。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |

## qa_messages

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | message id。 |
| `task_id` | `TEXT NOT NULL` | 所属 task，外键指向 `qa_tasks(id)`。 |
| `turn_id` | `TEXT` | 归属的 turn。系统级消息可以为空。 |
| `role` | `TEXT NOT NULL` | 消息角色，例如 `user`、`assistant`、`system`。 |
| `content` | `TEXT NOT NULL` | 消息正文。 |
| `metadata_json` | `TEXT NOT NULL` | 消息附加信息 JSON。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |


## qa_turns

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | turn id。 |
| `task_id` | `TEXT NOT NULL` | 所属 task，外键指向 `qa_tasks(id)`。 |
| `status` | `TEXT NOT NULL` | turn 状态，例如 `queued`、`in_progress`、`cancelling`、`completed`、`cancelled`、`failed`。 |
| `agent_completion_id` | `TEXT` | agent service completion id，用于 best-effort cancel。 |
| `user_message_id` | `TEXT` | 本轮对应的用户 message id。 |
| `error_message` | `TEXT` | 本轮失败时的错误信息。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |
| `updated_at` | `TEXT NOT NULL` | 最近更新时间。 |
| `completed_at` | `TEXT` | 进入终态的时间。 |

## qa_events

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | event id。 |
| `task_id` | `TEXT NOT NULL` | 所属 task，外键指向 `qa_tasks(id)`。 |
| `turn_id` | `TEXT` | 归属的 turn。task 级事件可以为空。 |
| `sequence` | `INTEGER NOT NULL` | task 内递增序号，用于 SSE 续传。 |
| `event_type` | `TEXT NOT NULL` | 事件类型，例如 `task.created`、`agent.event`、`turn.completed`。 |
| `status` | `TEXT NOT NULL` | 写入事件时的 task status 快照。 |
| `stage` | `TEXT NOT NULL` | 写入事件时的 task stage 快照。 |
| `payload_json` | `TEXT NOT NULL` | 事件 payload JSON。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |

