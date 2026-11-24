# 所有权划分与创建轮次

返回 [SessionManager 架构](../SESSION_MANAGER.md)。

## 调用关系与所有权

```text
FastAPI lifespan -> SessionRegistry.start -> 扫描遗留运行状态
HTTP handler -> SessionRegistry -> DocumentResourceClient（上传/删除文件时）
HTTP handler -> SessionManager 命令队列（create/cancel/attach/detach）
SessionManager._handle_create -> 冲突检查、分配 turn_id -> 创建 TurnRuntime（携带用户消息）
  -> runtime.start() -> await runtime.begun（begin 事务提交后返回）
TurnRuntime（自治）-> AgentClient -> 独立 agent gRPC 服务
TurnRuntime -> 工具组配对 -> 事务写 chat_messages -> 更新 TurnView -> publish -> manager.broadcast -> Subscription
HTTP handler -> session_history.build_snapshot -> 首帧 -> Subscription.receive -> SSE
FastAPI shutdown -> registry.close -> manager.close -> runtime.cancel / wait_closed
```

| 状态 | 归属 | 说明 |
| --- | --- | --- |
| session 行、`active_turn_id`、订阅者 | manager | session 级，跨轮存在 |
| 轮内 seq、工具组配对、`TurnView`、gRPC call | runtime | turn 私有，随轮生灭 |
| `chat_messages` 写入 | runtime | 活跃轮唯一 + per-turn seq，无第二个写者 |
| turn 创建与用户消息写入 | runtime `begin` 事务 | manager 只做冲突检查和分配 `turn_id`，落库随 begin 提交 |
| 轮终态与 `chat_turns`/`chat_sessions` 收口 | runtime | `update_turn_status_if_current` 条件更新并同事务清 `active_turn_id` |

- manager 对 runtime 的唯一反向通道为 `runtime.cancel()`（仅设标志并取消 gRPC call，不入队、不打断在途写事务）。
- runtime 不持有 manager 引用，数据依赖（`session_id`、`agent_client`、`database`）与回调（`refresh`、`publish`、`fail`）经构造注入；`broadcast` 为 asyncio 单线程原子语义。

## 核心文件职责

| 文件 | 输入、处理与输出 |
| --- | --- |
| `routes/chat.py` | JSON/multipart 校验，调用 `get_or_create` + manager 命令，输出 SSE 或 JSON |
| `session_registry.py` | Manager 状态机（`CREATING`/`READY`/`CLOSING`）、加载权、回收与启动恢复，不含业务逻辑 |
| `turn_runtime.py` | 自治执行体：建轮事务、事件配组落库、终态收口与广播，自带事务壳 |
| `session_manager.py` | 6 类命令 FIFO 串行、订阅、`pending_cancel` 补发、`fail` 损坏出口及非入队只读通道 |
| `turn_view.py` | 过程事件折叠成当前轮 items，输出深拷贝快照 |
| `subscription.py` | 独立有界队列，发布不阻塞，等待者取消不丢事件 |
| `session_history.py` | 读取 `chat_messages` 与 `chat_turns` 渲染历史轮，不常驻 manager |
| `agent_client.py` | protobuf 请求与响应转换，保留可取消原 call |

## 创建轮次（Exclusive-Create）

```text
POST /chat/completion（content、session_id、run_options）
  -> Registry 取得创建权（不存在时锁内写 CREATING，锁外创建/恢复 Manager；无 session_id 新建）
  -> manager 校验内容与有限正数超时，确认无活跃轮（failed 会话需新文件），分配 turn_id 并构造 runtime
  -> runtime.begin 事务：写 turn、用户消息、置 in_progress、认领 active_turn_id
  -> 等待 begun 信号确认提交后登记订阅并返回
```

- 每次 POST 均建新轮，有活跃轮时冲突拒绝；首帧前断线且未拿到 `session_id` 时重提可能建独立会话（不做去重）。
- 创建权为 exclusive-create：`CREATING` 期间并发请求立即冲突；显式取消创建协程会 abort 创建权并由创建方关闭未注册 manager（浏览器断开不等同协程取消）。冷 `GET /resume` 共用该入口。
