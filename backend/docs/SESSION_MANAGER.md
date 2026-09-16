# SessionManager、gRPC 执行与页面恢复

本文记录已落地的 backend 架构，分层对齐公开 Codex（53c542d9）的 core/app-server 边界：每个已加载 session 对应唯一 manager（≈ app-server ThreadState），只拥有 session 级状态和 create/cancel/attach 三个命令；每轮一个 TurnRuntime（≈ core 的 Session+turn 循环）自治执行，拥有轮内全部状态。历史从数据库恢复，过程事件不落库。

## 1. 调用关系与所有权

```text
FastAPI lifespan → SessionRegistry.start → 扫描遗留运行状态
HTTP handler → SessionRegistry → DocumentResourceClient（上传/删除文件时）
HTTP handler → SessionManager 命令队列（create/cancel/attach/detach）
SessionManager._handle_create → 冲突检查、分配 turn_id → 创建 TurnRuntime（携带用户消息） → runtime.start() → await runtime.begun（begin 事务提交后返回）
TurnRuntime（自治）→ AgentClient → 独立 agent gRPC 服务
TurnRuntime → 工具组配对 → 事务写 chat_messages → 更新 TurnView → publish 回调 → manager.broadcast → Subscription
HTTP handler → session_history.build_snapshot → 首帧 → Subscription.receive → SSE
FastAPI shutdown → registry.close → manager.close → runtime.cancel/wait_closed
```

所有权划分（对齐 Codex 的 core/app-server 职责边界）：

| 状态 | 归属 | 说明 |
| --- | --- | --- |
| session 行、active_turn_id、订阅者 | manager | session 级，跨轮存在 |
| 轮内 seq、工具组配对、TurnView、gRPC call | runtime | turn 私有，随轮生灭 |
| chat_messages 写入 | runtime | 活跃轮唯一 + per-turn seq，无第二个写者 |
| turn 创建与用户消息写入 | runtime begin 事务 | manager 只做冲突检查和分配 turn_id，落库随 begin 提交 |
| 轮终态写入 | runtime | `update_turn_status_if_current` 条件更新，取消/失败/完成只有一个赢家 |
| chat_turns/chat_sessions 收口 | runtime 事务内 | 同事务清 active_turn_id |

manager 对 runtime 的唯一反向通道是 `runtime.cancel()`：只设标志并取消 gRPC call，不进队列、不打断在途写事务。runtime 不持有 manager 引用，依赖以启动参数注入：`session_id`、`agent_client` 是数据依赖；`write`（事务提交并刷新 session/resources 缓存）、`publish`（事件广播）、`fail`（损坏标记）是 manager 注入的回调通道。broadcast 为 asyncio 单线程内同步语义，原子。

| 文件 | 输入、处理与输出 |
| --- | --- |
| routes/chat.py | JSON/multipart 校验，调用 get_or_create + manager 命令（create/attach/cancel），生成 SSE 或 JSON |
| session_registry.py | Manager 状态机（CREATING/READY/CLOSING）与加载权；回收与启动恢复 |
| turn_runtime.py | 自治执行体：begin 事务、agent 事件配组落库、终态收口、广播；依赖经构造参数注入，不引用 manager |
| session_manager.py | create/cancel/attach 三命令 FIFO 串行；订阅管理；终态广播的 pending_cancel 补发；向 runtime 注入 write/publish/fail 回调（_runtime_commit/_runtime_publish） |
| turn_view.py | 过程事件折叠成当前轮 items，输出深拷贝快照 |
| subscription.py | 独立有界队列，发布不阻塞，等待者取消不丢事件 |
| session_history.py | 读取 chat_messages 与 chat_turns 渲染历史轮，不常驻 manager |
| agent_client.py | 现有 protobuf 请求与响应转换，保留可取消原 call |

## 2. 创建轮次

```text
POST /chat/completion 输入 content、session_id、run_options
  → Registry 只负责取得创建权并返回唯一 manager；manager 校验内容和有限正数执行超时
  → 请求协程取得创建权：不存在时锁内写入 CREATING，锁外创建/恢复 Manager
  → 无 session_id：创建 session；有则加载对应唯一 manager
  → manager 检查无活跃轮；failed 会话要求新文件；分配 turn_id 并构造携带用户消息的 runtime
  → runtime.begin 事务：创建 turn、用户消息、turn.created/message.created、置 in_progress、认领 active_turn_id
  → 命令在 begun 信号上等待事务提交，之后登记本次请求的订阅并返回
```

每次 POST 都创建新轮次；同一 session 有活跃轮时拒绝新提交。断线后使用 session_id 调用 resume。首帧前丢失连接且尚未拿到 session_id 时，重新提交可能产生独立会话，当前不提供提交去重。创建权是 exclusive-create：Manager 处于 CREATING 时其他请求立即冲突，不等待也不共享创建过程。建轮事务由 runtime 的 begin 执行，命令协程在 begun 信号上等待提交后返回：响应先于提交会打开丢消息窗口，不等待则并发 create 会双建轮。

显式取消创建中的请求协程会 abort 创建权，由创建方关闭尚未注册的 manager；下一次请求可重新创建/恢复。浏览器断开本身不等同于请求协程被取消。GET /resume 对已回收或重启后的 session 与 complete 共用同一创建入口。

## 3. 资源与执行

```text
SessionRegistry.upload_files/remove_file（会话资源变更）
  → await DocumentResourceClient.prepare_resources
  → SessionManager 事务替换资源引用
  → 资源变更完成后才允许下一轮使用新引用

TurnRuntime.run（自治）
  → begin 事务：创建 turn 和用户消息、置 in_progress、认领 active_turn_id、按轮序读取 chat_messages
  → AgentClient.chat_completion(resources, messages, run_options)
  → 每个事件 _on_event：校验 → 配组 → 配齐则事务写 chat_messages → TurnView → broadcast
  → completion.completed/failed/cancelled → _finish 写终态事务并清 active_turn_id
  → 异常/提前流结束/取消 → _finish 收口（cancelled 或 failed）
```

文件上传和删除在独立的 document service 中完成，成功后 backend 原子替换 session 资源引用；轮次执行只调用 agent service，不重复准备资源。资源准备失败不会启动轮次，调用方可重试上传或删除。

gRPC 分别使用 document service 的 PrepareResources 与 agent service 的 ChatCompletion；取消使用原 call.cancel()。没有 CancelCompletion、GetCompletion 或 agent 端 resume RPC。agent_completion_id 用于关联，本身不能重新接入远端运行。

## 4. 串行与事务边界

串行化分两层，对齐 Codex 的"core 串行化 op、app-server 串行化投影"：

- manager 命令队列：create/cancel/attach/detach 编码为 Command(name, args, reply) 进入有界 FIFO 队列，_run 是唯一消费者。对外业务入口只有 create/cancel/attach，内容和 run_options 校验在 create 入口完成；detach/close 是生命周期管道。外部命令队列满直接拒绝；调用方协程取消不撤销已入队命令，handler 产生但无人接收的订阅由 _run 统一回收。
- runtime 内部串行：单任务顺序处理事件并顺序 await 每次写，无需应用层写锁；每次写独占一个线程池线程，thread-local 连接保证同一连接上事务不重叠，跨连接写竞争由 SQLite 文件锁和 busy_timeout 排队。runtime 的写失败经 `manager.fail()` 标记损坏：拒绝后续命令、取消执行、关闭订阅。

cancel 语义对齐 Codex 的 interrupt：`_handle_cancel` 校验轮次身份后登记 `pending_cancel` 等待者并调 `runtime.cancel()`，命令即返回等待；runtime 观察标志后自己写 cancelled 终态并广播，manager 在 broadcast 终态时补发 cancel 响应。已终结的轮次返回原终态。

service 的数据查询和写入统一调用 CRUD，不直接执行 SQL。每个写事务放入一次 asyncio.to_thread，使用线程内连接、crud.transaction 和 commit=False CRUD；CRUD 内部负责 BEGIN IMMEDIATE、提交及异常回滚。成功提交后才更新 TurnView、广播。

损坏 manager 当前不会在线自动重建；backend 重启扫描持久化状态收口遗留轮次。投影更新异常同样停止该 manager，避免数据库与内存分歧后继续服务。

不同 session 可并发处理，但 SQLite 写事务仍由数据库协调。当前必须单 backend worker；进程内唯一 manager 不能解决多进程 owner 问题。

## 5. 稳定模型上下文

```text
user 输入 → 独立完整消息提交
model_message.started/delta → 仅过程事件和展示
model_message.done → 以完整正文为准
  → 无工具：单条 assistant 提交
  → 有工具：校验原始调用 ID、名称和参数，暂存待配对组
tool_completed/failed → 按原 call_id 配对实际结果
  → 未配齐：仅保存过程
  → 配齐：同一事务提交 assistant + 按原调用顺序排列的全部 tool
下一轮 begin 命令 → 只读取 chat_messages，不拼接过程事件
```

同名工具也按 ID 独立匹配；结果乱序到达不改变稳定消息顺序。未知、重复调用或没有实际结果的工具终态不能补造数据。组提交与该事件入库同一事务，失败时没有半组或提前广播。

取消、执行失败或不完整终结丢弃未配齐组，保留此前完整消息。completion.completed 只收口轮次，不重复保存 assistant。

## 6. TurnView 和订阅

TurnView 归 runtime 所有，累积本轮的用户消息、模型尝试、工具和重试状态。delta 追加，done 用完整正文覆盖；重试按 message_id 分开，终结时未完成 item 标为 interrupted。终态广播后 manager 释放 runtime 引用，轮内状态随之消亡。

每个页面一条 Subscription，由 manager 持有；runtime 通过 `manager.broadcast` 发布。publish 深拷贝事件且不等待页面消费；溢出关闭该连接并清空队列，不影响其他页面或执行。receive 等待通知后取队列，心跳超时取消等待不会偷走下一条事件。

内存不是所有历史的缓存，但当前轮展示、工具配对和模型请求本身可能随当前工作量增长；有界订阅不等于整个 session 固定内存大小。

## 7. Resume 的一致性

```text
GET /resume → manager.attach 在串行命令中：
  1. 读取已存在的 turn id 列表（冻结快照范围）
  2. 捕获 session 状态、资源、当前轮展示副本（若存在）
  3. 注册独立订阅，后续新事件进入队列
请求侧 build_snapshot：
  4. 读取 chat_messages（按 sequence）与 chat_turns（状态和 error）
  5. 只渲染冻结列表内的轮次，按 turn 分组生成 items；排除当前轮
  6. 附加当前轮内存副本，检查快照预算并发送 session.snapshot
  7. 消费订阅队列增量
```

过程事件不落库，历史轮由 chat_messages 与 chat_turns 渲染：user/assistant 消息直接成项，assistant 的 tool_calls_json 还原工具调用列表，tool 消息按内容区分成功与失败。取消或失败轮次中未配齐的工具组没有消息行，对应展示项不再出现；turn 的终态错误来自 chat_turns.error。

冻结 turn id 列表划分数据库前缀与订阅增量：attach 之后新建的轮不进入首帧，只经订阅送达；查询期间旧轮完成会反映为数据库中的终态，当前轮始终以捕获副本为准。历史查询期间的变化不会造成重复或遗漏。

历史读取在命令循环外，避免大查询阻塞 cancel。查询出错、30 秒超时或构造期间订阅溢出时释放订阅，不发送不完整快照。历史仅在响应构造时加载；首帧编码后释放历史对象与当前轮副本。

本次 SSE 跟随首帧中的活跃轮，到其终态后关闭；空闲会话只返回一帧。页面重开时重新订阅现有 manager 或冷加载 manager，不重建仍在运行的 gRPC call。完整接口见 [API.md](API.md)。

## 8. 取消、卸载与重启

cancel 必须同时携带 session_id 和 turn_id。Registry.get 只获取现有 READY manager，不触发加载：会话空闲已被回收时直接返回 404。manager 登记 pending_cancel 后调 `runtime.cancel()`（设标志 + call.cancel()），响应在 runtime 广播终态后补发；已终结的轮次直接返回原终态。取消不撤销在途写事务：runtime 单任务顺序执行写，begin 事务提交后终态事务才执行，未配齐组随 runtime 消亡被丢弃。

取消后 runtime 不再接受新事件（`_on_event` 首查 cancel_requested），旧 call 取消后仍到达的事件不能污染数据。即使 runtime 尚未执行第一行就取消，run 的收口分支仍写终态并广播，不留悬挂句柄。

detach 只关闭该订阅。manager 只有在无活跃轮、runtime、订阅和待处理命令时才能按空闲期限回收；回收先把 entry 置为 CLOSING，锁外关闭后移除，此间该 session 的操作收到冲突。冷加载只读取会话摘要和资源，历史仍由 resume 按需查询。

启动时将遗留活跃轮标为 failed，错误 backend_restarted；processing 会话标为 failed，其余遗留运行会话回到 ready。不会自动重新调用 agent 或重做工具。页面恢复不等于进程级执行断点恢复。

## 9. 默认容量和当前边界

| BackendSettings 字段 | 默认值 |
| --- | --- |
| session_command_limit | 64 |
| subscription_max_events | 256 |
| subscription_max_bytes | 4 MiB |
| snapshot_max_bytes | 32 MiB |
| session_idle_seconds | 60 秒 |
| sse_heartbeat_seconds | 15 秒 |
| upload_max_bytes / upload_max_files | 32 MiB / 20 |

这些新增参数通过 BackendSettings 构造配置，目前没有对应环境变量映射。快照预算检查最终序列化大小；当前无分页或历史压缩。

当前单进程、单用户使用，未接入租户鉴权。前端仍需迁移旧 /qa/tasks 协议。agent 与 agent_proto 保持独立，Agent 合并计划已取消。

## 10. 验证与参考

行为测试覆盖创建独占与中断回滚、CLOSING 冲突、单例加载、取消后迟到事件、快照渲染与边界、真实 SQLite 事务回滚、工具乱序配对、慢订阅、提前取消收尾、冷恢复和启动收口。gRPC 测试使用本地真实服务、protobuf 序列化与有效 DOCX 样本；ASGI 测试验证断开后继续执行。各测试文件说明位于 backend/tests/docs/，与开发文档分离。

设计参考公开 Codex 固定版本 53c542d944c705f3a66780a19223223bee57cbb6，分层对齐其 core/app-server 边界：
- [thread_state.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/thread_state.rs)（ThreadState 投影 + pending_interrupts 补发模式）
- [thread_lifecycle.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/request_processors/thread_lifecycle.rs)（listener 单消费者、恢复与事件顺序）
- [thread_unsubscribe.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/tests/suite/v2/thread_unsubscribe.rs)

借鉴点：执行态归执行侧（core/Session ↔ runtime）、app-server 只持投影与连接路由（ThreadState ↔ manager）、取消是单向信号且终态由执行侧写入、resume 用持久化历史投影合并内存活 turn。本仓库的 SQLite 事务、SSE 订阅、Python 队列为本地适配，不代表 Codex 完整实现。

Registry 不维护服务关闭标志，也不以服务关闭为由拒绝创建或加载。应用退出由 lifespan 调用 close 清理资源；manager 与订阅仍保留各自的生命周期状态。
