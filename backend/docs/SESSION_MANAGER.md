# SessionManager、gRPC 执行与页面恢复

本文记录已落地的 backend 架构：每个已加载 session 对应唯一 manager，统一串行处理创建、取消、agent 事件及订阅；执行任务独立于 HTTP 连接。manager 只缓存当前轮展示，历史从数据库恢复。

## 1. 调用关系与所有权

```text
FastAPI lifespan → SessionRegistry.start → 扫描遗留运行状态
HTTP handler → SessionRegistry → SessionManager 的命令队列
SessionManager → TurnRuntime → AgentClient → 独立 agent gRPC 服务
TurnRuntime → manager.agent_event → 数据库事务 → TurnView → Subscription
HTTP handler → session_history.build_snapshot → 首帧 → Subscription.receive → SSE
FastAPI shutdown → registry.close → manager.close → runtime.cancel/wait_closed
```

Registry 持有 manager；manager 持有执行句柄与订阅；runtime 持有原始 gRPC call。complete 直接执行校验和会话创建，不另建受理任务；已启动的 runtime 独立于页面连接。

| 文件 | 输入、处理与输出 |
| --- | --- |
| routes/chat.py | JSON/multipart 校验，调用 complete/attach/cancel，生成 SSE 或 JSON |
| session_registry.py | session_id 查找或单次加载；回收与启动恢复 |
| session_manager.py | 命令按 FIFO 执行；校验轮次身份，事务提交后更新内存及广播 |
| turn_runtime.py | 文件准备、读取模型输入、消费事件，最终汇报 WorkerEnded |
| turn_view.py | 过程事件折叠成当前轮 items，输出深拷贝快照 |
| subscription.py | 独立有界队列，发布不阻塞，等待者取消不丢事件 |
| session_history.py | 捕获上下文加数据库历史，输出完整页面快照 |
| agent_client.py | 现有 protobuf 请求与响应转换，保留可取消原 call |

## 2. 创建轮次

```text
POST /chat/completion 输入 content、可选 session_id/files/run_options
  → Registry 校验内容、文件格式和容量、有限正数执行超时
  → 请求协程执行受理逻辑，并持有创建锁
  → 无 session_id：创建 session；有则加载对应唯一 manager
  → manager 检查无活跃轮；failed 会话要求新文件
  → 同一事务创建 turn、用户消息、turn.created/message.created，设置 active_turn_id
  → 登记本次请求的订阅并启动 runtime
```

每次 POST 都创建新轮次；同一 session 有活跃轮时拒绝新提交。断线后使用 session_id 调用 resume。首帧前丢失连接且尚未拿到 session_id 时，重新提交可能产生独立会话，当前不提供提交去重。创建锁仍用于协调创建、空闲回收与服务关闭。

显式取消请求协程会传播到受理逻辑；已经入队的 manager 命令仍按其生命周期收尾。浏览器断开本身不等同于请求协程被取消。冷加载由独立 loading task 持有，调用者取消后仍会把 manager 注册到 Registry，避免无 owner 的执行对象。

## 3. 资源与执行

```text
TurnRuntime.run
  → 有新文件：await AgentClient.prepare_resources
  → manager.resources_prepared 校验轮次身份，事务替换资源引用
  → manager.start_turn 设置 in_progress，按 sequence 读取 chat_messages
  → AgentClient.chat_completion(resources, messages, run_options)
  → 每个事件 await manager.agent_event，再读取下一个
  → 正常终态停止读取；异常/提前流结束通过 WorkerEnded 收口失败
```

有新文件时会话为 processing，轮次为 queued。准备成功后才启动模型；准备失败或期间取消会将 session 标为 failed，下一次需提供新文件。资源准备属于本轮任务，不另建长期资源 worker。

gRPC 只使用现有 PrepareResources 与 ChatCompletion；取消使用原 call.cancel()。没有 CancelCompletion、GetCompletion 或 agent 端 resume RPC。agent_completion_id 用于关联，本身不能重新接入远端运行。

## 4. 串行与事务边界

同一 manager 的创建、取消、Attach、事件、收尾通过一个有界 FIFO 队列。网络读取不占命令循环；runtime 每发一个事件等待确认，限制待处理事件积压。取消等待当前命令完成，不依赖独立优先队列。

service 的数据查询和写入统一调用 CRUD，不直接执行 SQL。每个写命令把完整 SQLite 事务放入一次 asyncio.to_thread，使用线程内连接、crud.transaction 和 commit=False CRUD；CRUD 内部负责 BEGIN IMMEDIATE、提交及异常回滚。成功提交后才能推进 last_event_seq、更新 TurnView、广播；SQL 异常回滚并标记 manager 损坏，取消执行、关闭订阅。

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
下一轮 start_turn → 只读取 chat_messages，不拼接 chat_events
```

同名工具也按 ID 独立匹配；结果乱序到达不改变稳定消息顺序。未知、重复调用或没有实际结果的工具终态不能补造数据。组提交与该事件入库同一事务，失败时没有半组或提前广播。

取消、执行失败或不完整终结丢弃未配齐组，保留此前完整消息。completion.completed 只收口轮次，不重复保存 assistant。

## 6. TurnView 和订阅

TurnView 缓存一个当前 turn 的用户消息、模型尝试、工具和重试状态。delta 追加，done 用完整正文覆盖；重试按 message_id 分开，终结时未完成 item 标为 interrupted。终态持久化并广播后释放当前轮缓存。

每个页面一条 Subscription，拥有独立事件数与字节预算。publish 深拷贝事件且不等待页面消费；溢出关闭该连接并清空队列，不影响其他页面或执行。receive 等待通知后取队列，心跳超时取消等待不会偷走下一条事件。

内存不是所有历史的缓存，但当前轮展示、工具配对和模型请求本身可能随当前工作量增长；有界订阅不等于整个 session 固定内存大小。

## 7. Resume 的一致性

```text
GET /resume → manager.attach 在串行命令中：
  1. 捕获 session 状态、资源、内部事件水位 N
  2. 深拷贝当前轮展示（若存在）
  3. 注册独立订阅，后续新事件进入队列
请求侧 build_snapshot：
  4. 调用 crud.iter_events_through 逐条查询 sequence <= N 的事件，排除已捕获的当前轮
  5. 按 turn 重放 TurnView，附加当前轮副本
  6. 检查快照预算并发送 session.snapshot
  7. 消费队列中的 N 之后增量
```

内部 N 仅用于划分数据库前缀与内存增量，不暴露客户端游标。历史查询期间旧轮完成甚至新轮开始，都不会改动已捕获副本；后续变化位于订阅队列中。

历史读取在命令循环外，避免大查询阻塞 cancel。查询出错、30 秒超时或构造期间订阅溢出时释放订阅，不发送不完整快照。历史仅在响应构造时加载；首帧编码后释放历史对象与当前轮副本。

本次 SSE 跟随首帧中的活跃轮，到其终态后关闭；空闲会话只返回一帧。页面重开时重新订阅现有 manager 或冷加载 manager，不重建仍在运行的 gRPC call。完整接口见 [API.md](API.md)。

## 8. 取消、卸载与重启

cancel 必须同时携带 session_id 和 turn_id。manager 先提交 cancelled、清空 active_turn_id、清理未配齐组并广播，再取消对应 runtime。已经终结的轮次返回原终态。

runtime 事件携带 turn_id 和 generation，manager 同时检查活跃轮和本地状态。旧 call 取消后仍到达的事件不能污染新轮。即使 runtime 尚未执行第一行就取消，完成回调仍汇报收尾并释放句柄。

detach 只关闭该订阅。manager 只有在无活跃轮、执行句柄、订阅和待处理命令时才能按空闲期限回收。冷加载只读取会话摘要、资源和水位，历史仍由 resume 按需查询。

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

这些新增参数通过 BackendSettings 构造配置，目前没有对应环境变量映射。快照预算同时检查历史事件读取量与最终序列化大小；当前无分页或历史压缩。

当前单进程、单用户使用，未接入租户鉴权。前端仍需迁移旧 /qa/tasks 协议。agent 与 agent_proto 保持独立，Agent 合并计划已取消。

## 10. 验证与参考

行为测试覆盖单例加载、请求取消、独立提交、取消后迟到事件、快照边界、真实 SQLite 事务回滚、工具乱序配对、慢订阅、提前取消收尾、冷恢复和启动收口。gRPC 测试使用本地真实服务、protobuf 序列化与有效 DOCX 样本；ASGI 测试验证断开后继续执行。各测试文件说明位于 backend/tests/docs/，与开发文档分离。

设计参考公开 Codex 固定版本 53c542d944c705f3a66780a19223223bee57cbb6：
- [thread_state.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/thread_state.rs)
- [thread_lifecycle.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/request_processors/thread_lifecycle.rs)
- [thread_unsubscribe.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/tests/suite/v2/thread_unsubscribe.rs)

借鉴点是恢复与事件串行衔接、连接与执行生命周期分离。本仓库的 SQLite 水位、SSE、Python 队列为本地适配，不代表 Codex 完整实现。

Registry 不维护服务关闭标志，也不以服务关闭为由拒绝创建或加载。应用退出由 lifespan 调用 close 清理资源；manager 与订阅仍保留各自的生命周期状态。
