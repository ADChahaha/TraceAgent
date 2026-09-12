# Backend 设计

backend 管理多轮 session、稳定模型消息和页面恢复，独立 agent 通过 gRPC 执行单次 turn。每个已加载 session 有唯一 SessionManager，串行处理创建、取消、事件和订阅；网络等待位于独立 TurnRuntime。浏览器断开只释放订阅。

## 调用关系

```text
POST /chat/completion → routes/chat.py 校验输入
  → SessionRegistry.complete 获取唯一 manager
  → SessionManager 事务创建 turn、用户消息、事件
  → TurnRuntime 准备资源 → AgentClient.chat_completion → gRPC
  → agent 事件交回 manager → 校验身份和状态 → 事务落库
  → TurnView 更新当前轮 → Subscription 广播 → SSE

GET /resume → manager.attach 捕获当前轮副本、内部水位并登记订阅
  → session_history.build_snapshot 读取水位之前的历史
  → 合并历史和当前轮 → 首帧快照 → 排队及后续增量

POST /cancel → manager 事务提交 cancelled、清空 active_turn_id
  → TurnRuntime.cancel → 原 gRPC call.cancel()
  → 旧轮迟到事件因身份或状态不匹配被丢弃
```

## 模块边界

| 文件 | 职责 |
| --- | --- |
| routes/chat.py | 三个 API、输入校验、快照和 SSE、断开时 detach |
| session_registry.py | 唯一加载、空闲回收、启动恢复和关闭 |
| session_manager.py | 串行命令、事务、稳定消息配对和状态转换 |
| turn_runtime.py | 资源准备和 gRPC 消费，向 manager 汇报事件及收尾 |
| turn_view.py | 当前轮展示投影，历史恢复复用同一逻辑 |
| subscription.py | 每连接独立有界队列，溢出只关闭慢连接 |
| session_history.py | 按固定数据库前缀读取历史，不常驻 manager |
| agent_client.py | agent_proto 与 grpc.aio 转换 |
| core/db.py、crud/crud.py | 线程内连接、事务和参数化 SQL |

Registry.complete 直接执行校验和会话创建，不创建独立受理任务；真正的后台执行由 TurnRuntime.start 创建。显式取消请求协程可中断尚未交给 manager 的受理过程。

## 事务和生命周期

五张表为 chat_sessions、chat_resources、chat_turns、chat_messages、chat_events，初始化不迁移旧 qa_* 数据。一个命令的写入在同一工作线程、同一事务完成；CRUD 的 commit=False 由外层提交，提交后才更新投影和广播。

chat_messages 只保存完整模型历史。工具组按原始 call_id 配齐实际结果后原子提交；取消丢弃未配齐组。chat_events 用于页面恢复，不能补回不完整模型上下文。

manager 只缓存当前 turn，终结后释放。SSE 在捕获的活跃轮终结时关闭，空闲会话只发送一次快照。无活跃轮、执行句柄、订阅及待处理命令时才回收 manager。backend 重启把遗留活跃轮标为 failed/backend_restarted，不重新执行 agent。

数据库事务失败会回滚并将 manager 标记损坏、取消执行、关闭订阅；当前没有自动重建损坏 manager。部署使用单 backend 进程、单用户；尚无跨进程 owner 协调和租户鉴权。旧 task 路由已删除，frontend 尚未迁移。

[详细设计](SESSION_MANAGER.md) · [接口](API.md) · [数据表](table.md)。Agent 合并方案已取消，AGENT_MERGE.md 仅为历史草案。

Registry 不维护服务关闭标志，也不以服务关闭为由拒绝创建或加载。应用退出由 lifespan 调用 close 清理资源；manager 与订阅仍保留各自的生命周期状态。
