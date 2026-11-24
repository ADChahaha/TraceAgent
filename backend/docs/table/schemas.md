# Backend 数据表结构与约束

返回 [Backend 数据表](../table.md)。

## `chat_sessions`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 会话 ID |
| `status` | `TEXT NOT NULL` | 会话粗粒度状态（`processing`/`ready`/`running`/`failed`） |
| `active_turn_id` | `TEXT` | 当前活跃 turn 辅助索引（非数据库锁或唯一并发事实来源） |
| `created_at` / `updated_at` | `TEXT NOT NULL` | 创建时间 / 最近更新时间 |

## `chat_resources`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 资源记录 ID |
| `session_id` | `TEXT NOT NULL` | 外键指向 `chat_sessions(id)` |
| `type` | `TEXT NOT NULL` | 资源类型（`raw`/`documents`/`index`，以返回引用为准） |
| `location` | `TEXT NOT NULL` | 资源位置或产物内容，原样存取 |
| `created_at` | `TEXT NOT NULL` | 创建时间 |

约束：`UNIQUE(session_id, type, location)` 防止同会话重复资源。

## `chat_turns`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | turn ID |
| `session_id` | `TEXT NOT NULL` | 外键指向 `chat_sessions(id)` |
| `status` | `TEXT NOT NULL` | `queued`/`in_progress`/`completed`/`cancelled`/`failed` |
| `agent_completion_id` | `TEXT` | agent completion 关联 ID（取消靠内存原 gRPC call，不能凭此重连） |
| `error` | `TEXT` | 终态错误说明（如 `backend_restarted`），随终态同事务写入 |
| `created_at` / `updated_at` / `completed_at` | `TEXT` | 创建（非空）/ 更新（非空）/ 终态时间（可空） |

## `chat_messages`

一行保存一条完整模型输入消息，一组表示一次原子提交（用户/无工具 assistant 各自成组；有工具调用时包含 1 条 assistant 及其全部 tool 结果）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | backend 消息 ID（不与 agent `message_id` 混用） |
| `session_id` / `turn_id` | `TEXT` | 归属 session 与复合外键 `(session_id, turn_id)` 指向 `chat_turns` |
| `sequence` | `INTEGER NOT NULL` | 轮内顺序（per-turn seq，`> 0`）；跨轮顺序由 `chat_turns` 创建顺序给出 |
| `group_id` / `group_index` | `TEXT` / `INTEGER` | 原子提交组标识（非空，按 `turn_id + message_id` 稳定生成）与组内序号（`>= 0`） |
| `role` | `TEXT NOT NULL` | `user`/`system`/`assistant`/`tool`（当前约束要求 `turn_id` 非空，不支持 `system`） |
| `content` | `TEXT NOT NULL` | 完整正文；tool 为实际结果 JSON 文本，允许模型正文为空 |
| `tool_calls_json` | `TEXT NOT NULL DEFAULT '[]'` | assistant 工具调用 JSON 数组（模型输入格式 `[{"id":...,"type":"function","function":{...}}]`）；非 assistant 必须为空数组 |
| `tool_call_id` / `name` | `TEXT` | tool 对应原始调用 ID 与工具名（tool 必填，非 tool 必须为空） |
| `created_at` | `TEXT NOT NULL` | 创建时间 |

- 数据库约束：`UNIQUE(turn_id, sequence)`、`UNIQUE(turn_id, group_id, group_index)`、同组非空 `tool_call_id` 唯一索引，以及 `chat_turns(session_id, id)` 唯一索引防跨会话关联。
- 活跃轮唯一保证同一 turn 只有一个写者（runtime）；数据库只校验行级结构，不能替代业务配对校验。
