# Backend 调用关系与模块边界

本页属 [Backend 设计](../DESIGN.md)，记录核心 HTTP/SSE 调用链、模块职责表与 `SessionRegistry` 生命周期。

## 核心调用关系

```text
POST /chat/completion -> routes/chat.py 校验输入
  -> SessionRegistry.get_or_create 复用或取得创建权，返回唯一 manager
  -> SessionManager.create_completion 校验并串行化 create 命令（事务在 TurnRuntime.begin）
     首帧捕获全部已存在轮次 ID，与 resume 一样合并完整历史
  -> 会话文件：manager.upload_files / remove_file 以队列命令串行执行
     （配额校验 -> DocumentResourceService gRPC -> 替换资源引用）
  -> TurnRuntime -> AgentClient.chat_completion -> AgentService gRPC
  -> agent 事件交回 manager -> 校验身份和状态 -> 事务落库
  -> TurnView 更新当前轮 -> Subscription 广播 -> SSE

GET /resume -> Registry 复用或恢复 manager；manager.attach 捕获当前轮副本和已存在轮次 ID 并登记订阅
  -> session_history.build_snapshot 读取 chat_messages 与 chat_turns 渲染历史轮
  -> 合并当前轮内存副本 -> 首帧快照 -> 后续增量

GET /chat/sessions/{id}/files/{resource_id}、.../documents、.../documents/content、.../documents/full、.../blocks
  -> manager 读取通道：raw 经 ObjectStore 按 location 读回；documents 归档按本会话引用解析，跨会话不可达
  -> full 由 document_view 按一级文档目录自然排序读取全部 Markdown 块并保留 key

POST /cancel -> Registry.get 取得现有 manager（只操作已加载会话）
  -> 提交 cancelled 终态、清空 active_turn_id -> TurnRuntime.cancel -> 原 gRPC call.cancel()
  -> 旧轮迟到事件因身份或状态不匹配被丢弃
```

## 模块边界

| 文件 | 职责 |
| --- | --- |
| `routes/chat.py` | 核心 HTTP/SSE 接口、输入校验、快照与流输出、断开时 detach |
| `session_registry.py` | Manager 的 `CREATING`/`READY`/`CLOSING` 状态机、加载权归属、回收和关闭 |
| `session_manager.py` | 串行命令、事务协调、稳定消息配对和状态转换 |
| `turn_runtime.py` | `AgentService` gRPC 消费，向 manager 汇报事件及收尾 |
| `turn_view.py` | 当前轮展示投影，历史恢复复用同一逻辑 |
| `subscription.py` | 每连接独立有界队列，溢出只关闭慢连接 |
| `session_history.py` | 读取 `chat_messages` 与 `chat_turns` 渲染历史轮，不常驻 manager |
| `agent_client.py` | `AgentService` protobuf 与 `grpc.aio` 转换，只负责 `ChatCompletion` |
| `document_client.py` | `DocumentResourceService` protobuf 与 `grpc.aio` 转换，只负责 `PrepareResources` |
| `core/db.py`、`crud/crud.py` | 线程内连接、事务和参数化 SQL |

## Registry 状态与关闭约束

- Registry 用每 session 的 Entry 状态协调 Manager 生命周期：不存在时当前请求取得创建权（`CREATING`），锁外完成加载后转 `READY`；`complete` 与 cold `resume` 共用该入口，`cancel` 只取现有 `READY` manager。
- 后台执行由 `TurnRuntime.start` 创建；创建请求被显式取消时 abort 创建权，由创建方关闭未注册 manager。
- Registry 不维护服务关闭标志，也不以服务关闭为由拒绝创建或加载；应用退出由 lifespan 调用 `close` 清理资源，manager 与订阅保留各自生命周期状态。
