# 取消卸载、容量阈值与参考实现

本页属 [SessionManager 架构](../SESSION_MANAGER.md)，汇总取消/回收/重启行为、`BackendSettings` 默认容量与设计参考。

## 取消、卸载与重启收口

- `cancel` 必须同时携带 `session_id` 与 `turn_id`。`Registry.get` 仅获取现有 `READY` manager，空闲已回收会话返回 404，不触发加载。
- 取消后 runtime 不再接受新事件（`_on_event` 首查 `cancel_requested`），旧 call 迟到事件不能污染数据；即使 runtime 未执行首行即被取消，收口分支仍写终态并广播，不留悬挂句柄。取消不撤销在途写事务。
- `detach` 只关闭对应订阅。manager 仅在无活跃轮、runtime、订阅及待处理命令时按空闲期限回收：entry 先置 `CLOSING`，锁外关闭后移除，期间请求收到冲突。冷加载只读会话摘要与资源，历史由 resume 按需查询。
- 服务启动时将遗留活跃轮标为 `failed`（`error="backend_restarted"`），`processing` 会话标为 `failed`，其余遗留运行会话回到 `ready`；不自动重试 agent 或工具，页面恢复不等同于进程断点恢复。
- Registry 不维护服务关闭标志，也不拒绝创建/加载；应用退出由 lifespan 调用 `close` 清理资源。

## 默认容量与边界

| `BackendSettings` 字段 | 默认值 |
| --- | --- |
| `session_command_limit` | 64 |
| `subscription_max_events` | 256 |
| `subscription_max_bytes` | 4 MiB |
| `snapshot_max_bytes` | 32 MiB |
| `session_idle_seconds` | 60 秒 |
| `sse_heartbeat_seconds` | 15 秒 |
| `upload_max_bytes` / `upload_max_files` | 32 MiB / 20 |

- 以上参数通过 `BackendSettings` 构造配置，目前无对应环境变量映射；快照预算检查最终序列化大小，当前无分页或历史压缩。
- 当前为单进程、单用户模式，无租户鉴权；`agent` 与 `agent_proto` 保持独立，Agent 合并计划已取消。

## 验证覆盖与参考实现

- 行为测试覆盖创建独占与中断回滚、`CLOSING` 冲突、单例加载、取消后迟到事件、快照渲染与边界、真实 SQLite 事务回滚、工具乱序配对、慢订阅、提前取消收尾、冷恢复与启动收口；gRPC 测试用本地真实服务与 DOCX 样本，ASGI 测试验证断连后继续执行（详见 `backend/tests/docs/`）。
- 分层设计参考公开 Codex 固定提交 `53c542d944c705f3a66780a19223223bee57cbb6`：
  - [thread_state.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/thread_state.rs)（`ThreadState` 投影与 `pending_interrupts` 补发模式）
  - [thread_lifecycle.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/src/request_processors/thread_lifecycle.rs)（单消费者、恢复与事件顺序）
  - [thread_unsubscribe.rs](https://github.com/openai/codex/blob/53c542d944c705f3a66780a19223223bee57cbb6/codex-rs/app-server/tests/suite/v2/thread_unsubscribe.rs)
- 借鉴点：执行态归执行侧（core/Session <-> runtime）、app-server 仅持投影与连接路由（ThreadState <-> manager）、取消为单向信号且终态由执行侧写入、resume 合并持久化历史与内存活 turn。SQLite 事务、SSE 订阅与 Python 队列为本地适配。
