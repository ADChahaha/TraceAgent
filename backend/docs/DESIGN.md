# Backend 设计

backend 管理多轮 session、稳定模型消息和页面恢复，独立 agent 通过 gRPC 执行单次 turn。每个已加载 session 有唯一 SessionManager，串行处理创建、取消、事件和订阅；网络等待位于独立 TurnRuntime。浏览器断开只释放订阅。

## 调用关系

```text
POST /chat/completion → routes/chat.py 校验输入
  → SessionRegistry.complete 复用或取得创建权，返回唯一 manager
  → SessionManager 事务创建 turn、用户消息、事件
  → TurnRuntime 准备资源 → AgentClient.chat_completion → gRPC
  → agent 事件交回 manager → 校验身份和状态 → 事务落库
  → TurnView 更新当前轮 → Subscription 广播 → SSE

GET /resume → Registry 复用或恢复 manager；manager.attach 捕获当前轮副本和已存在轮次 ID 列表并登记订阅
  → session_history.build_snapshot 读取 chat_messages 与 chat_turns 渲染历史轮
  → 合并当前轮内存副本 → 首帧快照 → 后续增量

POST /cancel → Registry.get 取得现有 manager，只操作已加载会话
  → manager 事务提交 cancelled、清空 active_turn_id
  → TurnRuntime.cancel → 原 gRPC call.cancel()
  → 旧轮迟到事件因身份或状态不匹配被丢弃
```

## 模块边界

| 文件 | 职责 |
| --- | --- |
| routes/chat.py | 三个 API、输入校验、快照和 SSE、断开时 detach |
| session_registry.py | Manager 的 CREATING/READY/CLOSING 状态机、加载权归属、回收和关闭 |
| session_manager.py | 串行命令、事务、稳定消息配对和状态转换 |
| turn_runtime.py | 资源准备和 gRPC 消费，向 manager 汇报事件及收尾 |
| turn_view.py | 当前轮展示投影，历史恢复复用同一逻辑 |
| subscription.py | 每连接独立有界队列，溢出只关闭慢连接 |
| session_history.py | 读取 chat_messages 与 chat_turns 渲染历史轮，不常驻 manager |
| agent_client.py | agent_proto 与 grpc.aio 转换 |
| core/db.py、crud/crud.py | 线程内连接、事务和参数化 SQL |

Registry 用每 session 的 Entry 状态协调 Manager 生命周期：不存在时由当前请求取得创建权（CREATING），锁外完成加载后转 READY；complete 和 cold resume 共用该入口，cancel 只取现有 READY manager。真正的后台执行由 TurnRuntime.start 创建；创建请求被显式取消时 abort 创建权，由创建方关闭未注册 manager。

## 数据访问边界

事务入口 transaction() 和业务 SQL 统一放在 crud/crud.py；service 通过 with crud.transaction(db) 将相关 CRUD 操作组合为一次原子提交。core/db.py 负责连接和数据库初始化：

```text
Registry.start → list_sessions_needing_recovery / list_unfinished_turns → 遗留轮次收口（error 写入 chat_turns）
Manager 创建或提交消息组 → get_next_message_sequence → 同事务插入完整消息
Manager 替换资源 → delete_resources(commit=False) → 同事务插入新资源
History.build_snapshot → list_turns + list_messages → 按 turn 分组渲染展示
```

过程事件不落库：事件只更新内存 TurnView 并广播订阅，页面恢复从 chat_messages 与 chat_turns 渲染。CRUD 不捕获数据库异常，交给 service 回滚与处理；事务内删除资源不自行提交。

## 事务和生命周期

四张表为 chat_sessions、chat_resources、chat_turns、chat_messages，初始化不迁移旧 qa_* 数据。一个命令的写入在同一工作线程、同一事务完成；CRUD 的 commit=False 由外层提交，提交后才更新投影和广播。

chat_messages 只保存完整模型历史。工具组按原始 call_id 配齐实际结果后原子提交；取消丢弃未配齐组。过程事件不持久化，页面恢复由消息与轮次状态渲染。

manager 只缓存当前 turn，终结后释放。SSE 在捕获的活跃轮终结时关闭，空闲会话只发送一次快照。无活跃轮、执行句柄、订阅及待处理命令时才回收 manager：entry 先从 READY 置为 CLOSING，锁外关闭后移除，此间该 session 的请求收到冲突。cancel 只操作已加载的 manager，空闲已回收会话返回 404。backend 重启把遗留活跃轮标为 failed/backend_restarted，不重新执行 agent。

数据库事务失败会回滚并将 manager 标记损坏、取消执行、关闭订阅；当前没有自动重建损坏 manager。部署使用单 backend 进程、单用户；尚无跨进程 owner 协调和租户鉴权。旧 task 路由已删除，frontend 尚未迁移。

[详细设计](SESSION_MANAGER.md) · [接口](API.md) · [数据表](table.md)。Agent 合并方案已取消，AGENT_MERGE.md 仅为历史草案。

Registry 不维护服务关闭标志，也不以服务关闭为由拒绝创建或加载。应用退出由 lifespan 调用 close 清理资源；manager 与订阅仍保留各自的生命周期状态。
