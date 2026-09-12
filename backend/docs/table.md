# Backend 数据表

`chat_events` 保存过程事件，供展示和 SSE 续传；`chat_messages` 设计为只保存可完整回传模型的稳定历史。普通完整消息单条提交；带工具调用的 assistant 与全部对应 tool 结果配齐后，在同一事务中一起提交。中断只丢弃尚未提交的组，不删除此前完整历史。

schema、CRUD 与 SessionManager 已接通，统一使用 `chat_*` 和 `session_id`。初始化只创建当前表，不迁移或删除旧 `qa_*` 表及数据。CRUD 默认自行提交；manager 使用 `commit=False` 将相关写入放在同一个事务中。

## chat_sessions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 会话 ID。 |
| `status` | `TEXT NOT NULL` | session 粗粒度状态，例如 `processing`、`ready`、`running`、`failed`。 |
| `active_turn_id` | `TEXT` | 当前活跃 turn 的辅助索引。不是数据库锁，也不是唯一并发事实来源。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |
| `updated_at` | `TEXT NOT NULL` | 最近更新时间。 |

## chat_resources

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 资源记录 ID。 |
| `session_id` | `TEXT NOT NULL` | 所属会话，外键指向 `chat_sessions(id)`。 |
| `type` | `TEXT NOT NULL` | 资源类型，如 raw、documents、index（以 agent 返回引用为准）。 |
| `location` | `TEXT NOT NULL` | 资源位置或产物内容，沿用当前 CRUD 的原样存取。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |

`UNIQUE(session_id, type, location)` 防止同一会话内重复资源。

## chat_messages

一行保存一条完整模型输入消息，一组表示一次原子提交。用户消息、系统消息和无工具调用的完整 assistant 各自成组；有工具调用时，一组包含一条 assistant 及其全部 tool 结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | backend 消息 id，不与 agent 的 message_id 混用。 |
| `session_id` | `TEXT NOT NULL` | 所属 session，外键指向 `chat_sessions(id)`。 |
| `turn_id` | `TEXT` | 所属 turn，通过 `(session_id, turn_id)` 复合外键关联 chat_turns；仅 system 角色可为空。 |
| `sequence` | `INTEGER NOT NULL` | session 内稳定消息顺序，与 chat_events.sequence 独立；整组提交时分配。 |
| `group_id` | `TEXT NOT NULL` | 原子提交组标识；agent 组按 turn_id + message_id 稳定生成，重放不重复写入。 |
| `group_index` | `INTEGER NOT NULL` | 组内顺序，从 0 开始；assistant 在前，tool 按原 tool_calls 顺序排列。 |
| `role` | `TEXT NOT NULL` | user、system、assistant 或 tool。 |
| `content` | `TEXT NOT NULL` | 完整正文；tool 为实际结果的 JSON 文本，允许模型正文为空。 |
| `tool_calls_json` | `TEXT NOT NULL DEFAULT '[]'` | assistant 的完整工具调用列表，保留原始 ID、名称和参数；其他角色为空数组。 |
| `tool_call_id` | `TEXT` | tool 对应的原始调用 ID；非 tool 消息为空。 |
| `name` | `TEXT` | tool 名称，非 tool 消息为空。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |

已实现的数据库约束：`UNIQUE(session_id, sequence)`、`UNIQUE(session_id, group_id, group_index)`，以及同组非空 tool_call_id 的唯一索引；sequence 大于 0，group_index 非负，group_id 非空。role 限定为表中四类；tool 必须有非空调用 ID 和名称，其他角色的这两个字段必须为空。tool_calls_json 必须是合法 JSON 数组，非 assistant 只能为空数组。复合外键依赖 chat_turns(session_id, id) 唯一索引，防止消息关联其他 session 的 turn。

业务已接入：tool_calls_json 使用模型输入格式 `[{"id":"call-a","type":"function","function":{"name":"read","arguments":"{}"}}]`，从 agent 的 id/name/args_json 转换并保留原始 ID。manager 校验配对完整性，在同一事务写完整组；同轮重复消息或未知、重复工具结果按协议错误处理。数据库只校验数组结构及行级约束，不能替代业务校验。

### 配对与提交

```text
backend 接收 agent event，并在 session manager 串行命令内检查本地状态
  → 已取消或终态：丢弃迟到事件，不提交稳定消息
  → model_message.started / delta：仅属于过程，不写 chat_messages
  → model_message.done：以完整快照为准，不重复拼接 delta
     ├─ 无 tool_calls：完整 assistant 作为单条组提交，无需等整轮 completion.completed
     └─ 有 tool_calls：按本轮 message_id 暂存 assistant，等待全部结果
  → tool_completed / tool_failed：按原始 tool_call_id 精确归入待提交组
  → 校验调用 ID 非空且唯一、每个调用恰好有一个结果、没有未知 ID
  → 全部配齐：同一短事务写 assistant + 全部 tool，分配稳定 sequence
  → 下一轮 start_turn 只按 sequence 读取 chat_messages
```

tool_failed 是真实的完整工具结果，可以参与配对；tool_started 不算结果。不得按工具名或到达顺序猜测配对，不得生成替代 call ID。无效或冲突结果不提交该组；不能通过省略缺失工具调用让一组看起来完整。用户输入在请求受理时以独立完整消息提交，不要求与回答配对。

### 中断边界

取消与组提交共用同一 session manager 的串行命令循环。当前事件若已进入临界区且使整组配齐，可先完成整组事务；取消先提交本地状态后，后续事件不能再写入。事务失败则整组回滚，不留下单独 assistant 或部分 tool 行。

例如 assistant 调用 A、B，只收到 A 就取消：assistant、A、B 这一组均不进入 chat_messages，不补造 B 的中断结果；此前已提交的用户消息和完整组保留。过程事件可仍存在 chat_events 中用于展示，但下一轮不能从 chat_events 补回这组不完整消息。暂存配对数据在取消、失败或流关闭时丢弃；进程退出前未提交的组也不属于稳定历史。

该表是中断后重建模型上下文的唯一持久化来源，不是取消后继续接受 agent 内容的通道；完成收尾不得把已经提交过的 assistant 再写一次。

### 跨轮读取与提交顺序

旧轮组提交、取消和新轮启动经同一 session manager 串行处理：旧轮最后一次合法事务提交 → 本地取消事务提交 → 新轮保存用户消息并读取 chat_messages 快照 → 锁外生成。新轮不能在旧轮仍可写消息时提前读取历史。

sequence 在同一命令的写事务中为整组分配并插入；唯一约束仅负责防止重复，不代替事务。旧 worker 始终检查自身 turn_id，取消后即使后台计算仍运行也不能补写。完整交接流程见 [DESIGN.md](DESIGN.md)。


## chat_turns

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | turn id。 |
| `session_id` | `TEXT NOT NULL` | 所属 session，外键指向 `chat_sessions(id)`。 |
| `status` | `TEXT NOT NULL` | turn 状态，例如 `queued`、`in_progress`、`completed`、`cancelled`、`failed`。 |
| `agent_completion_id` | `TEXT` | agent completion 关联 ID；取消依靠内存中的原 gRPC call，不能凭此 ID 重新接入执行。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |
| `updated_at` | `TEXT NOT NULL` | 最近更新时间。 |
| `completed_at` | `TEXT` | 进入终态的时间。 |

## chat_events

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | event id。 |
| `session_id` | `TEXT NOT NULL` | 所属 session，外键指向 `chat_sessions(id)`。 |
| `turn_id` | `TEXT` | 归属的 turn。session 级事件可以为空。 |
| `sequence` | `INTEGER NOT NULL` | session 内递增序号，供内部恢复边界使用；不暴露为客户端游标。 |
| `event_type` | `TEXT NOT NULL` | 事件类型，例如 `turn.created`、`model_message.delta`、`turn.completed`。 |
| `payload_json` | `TEXT NOT NULL` | 事件 payload JSON。 |
| `created_at` | `TEXT NOT NULL` | 创建时间。 |


`turn.created.payload_json` 当前为空对象，不保存请求去重元数据。
